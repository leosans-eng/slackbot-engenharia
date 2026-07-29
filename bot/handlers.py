"""Lógica de negócio do bot Slack."""

from __future__ import annotations

import logging
import os
import re
import shutil
import uuid
from datetime import date
from pathlib import Path

from slack_sdk import WebClient

from ferramentas.formatador_sinapi import Modelo, formatar_planilha
from ferramentas.formatador_sinapi.types import ResultadoFormatacao
from ferramentas.idebras import (
    MultiplosResultadosError,
    download_owner_photos,
    gerar_relatorio_pericias,
    hoje,
    ontem,
    parse_data,
    zip_to_pdf,
)
from bot.config import SlackConfig
from bot.files import baixar_arquivo_slack, enviar_arquivos_slack
from bot.state import ArquivoPendente, obter_planilha_pendente, registrar_planilha
from bot.usuarios import rotulo_usuario

logger = logging.getLogger(__name__)


def interpretar_modelo(texto: str) -> Modelo:
    """Interpreta o parâmetro do comando (/i9formatar modelo=1, /i9formatar 2, etc.)."""
    texto = (texto or "").strip().lower()
    if not texto:
        raise ValueError(
            "Informe o modelo: `/i9formatar 1`, `2` ou `3`."
        )

    match = re.search(r"(?:modelo\s*[=:]?\s*)?([123])\b", texto)
    if match:
        return Modelo(int(match.group(1)))

    raise ValueError(
        f"Modelo inválido: `{texto}`. Use `modelo=1`, `modelo=2` ou `modelo=3`."
    )


def registrar_arquivos_da_mensagem(
    user_id: str,
    channel_id: str,
    arquivos: list[dict],
    *,
    client: WebClient | None = None,
) -> ArquivoPendente | None:
    """Guarda a última planilha .xlsx encontrada na mensagem."""
    ultima: ArquivoPendente | None = None
    rotulo = rotulo_usuario(client, user_id) if client else f"usuário={user_id}"
    for arquivo in arquivos:
        from bot.files import eh_planilha_xlsx

        if not eh_planilha_xlsx(arquivo):
            continue
        nome = arquivo.get("name") or "planilha.xlsx"
        file_id = arquivo.get("id")
        if not file_id:
            continue
        registrar_planilha(user_id, channel_id, file_id, nome)
        ultima = ArquivoPendente(file_id=file_id, nome=nome)
        logger.info("Planilha registrada — %s — canal=%s — arquivo=%s", rotulo, channel_id, nome)
    return ultima


def processar_upload(
    caminho_entrada: str,
    modelo: Modelo | int,
    diretorio_saida: str | None = None,
) -> ResultadoFormatacao:
    saida = diretorio_saida or os.path.join(
        os.environ.get("SLACKBOT_TEMP_DIR")
        or os.environ.get("FORMATADOR_TEMP_DIR")
        or os.path.join(os.getcwd(), "tmp", "slack"),
        str(uuid.uuid4()),
    )
    os.makedirs(saida, exist_ok=True)
    return formatar_planilha(
        caminho_entrada,
        modelo=modelo,
        diretorio_saida=saida,
    )


def arquivos_para_enviar(resultado: ResultadoFormatacao) -> list[Path]:
    arquivos = [Path(resultado.caminho_excel)]
    if resultado.caminho_word:
        arquivos.append(Path(resultado.caminho_word))
    return arquivos


def executar_comando_formatar(
    client: WebClient,
    config: SlackConfig,
    channel_id: str,
    user_id: str,
    texto_comando: str,
) -> str:
    """
    Fluxo completo: resolve modelo → baixa planilha pendente → formata → envia arquivos.

    Retorna mensagem de status para o Slack (sucesso ou erro).
    """
    modelo = interpretar_modelo(texto_comando)

    pendente = obter_planilha_pendente(user_id, channel_id)
    if pendente is None:
        raise ValueError(
            "Nenhuma planilha `.xlsx` encontrada.\n"
            "Envie o arquivo neste canal ou DM *antes* de rodar o comando, "
            "por exemplo:\n"
            "1. Anexe `Planilha Sintética....xlsx`\n"
            f"2. `/i9formatar modelo={int(modelo)}`"
        )

    sessao_dir = os.path.join(config.diretorio_temporario, str(uuid.uuid4()))
    os.makedirs(sessao_dir, exist_ok=True)

    try:
        caminho_entrada = baixar_arquivo_slack(
            client,
            pendente.file_id,
            pendente.nome,
            sessao_dir,
        )
        resultado = processar_upload(
            str(caminho_entrada),
            modelo=modelo,
            diretorio_saida=sessao_dir,
        )
        gerados = arquivos_para_enviar(resultado)
        comentario = (
            #f"✅ {resultado.modelo.rotulo}" - Teste com emoji
            f" {resultado.modelo.rotulo}"
            + (f" — _{resultado.nome_obra}_" if resultado.nome_obra else "")
        )
        enviar_arquivos_slack(client, channel_id, gerados, comentario=comentario)

        linhas = [
            #f"✅ Formatação concluída — *{resultado.modelo.rotulo}*", - Teste com emoji
            f" Formatação concluída — *{resultado.modelo.rotulo}*",
        ]
        if resultado.nome_obra:
            linhas.append(f"Obra: _{resultado.nome_obra}_")
        linhas.append(f"Arquivos enviados: {len(gerados)}")
        for aviso in resultado.avisos:
            linhas.append(f"⚠️ {aviso}")
        return "\n".join(linhas)
    finally:
        shutil.rmtree(sessao_dir, ignore_errors=True)


def interpretar_argumentos_fotos(texto: str) -> tuple[str, int | None]:
    """Extrai nome do proprietário e índice opcional de `/fotos`."""
    texto = (texto or "").strip()
    if not texto:
        raise ValueError(
            "Informe o nome do proprietário.\n"
            "Exemplos:\n"
            "`/fotos João da Silva`\n"
            "`/fotos João da Silva index=2`"
        )

    index: int | None = None
    nome = texto

    match_index = re.search(
        r"(?:^|\s)(?:index|indice|índice)\s*[=:]?\s*(\d+)\s*$",
        texto,
        flags=re.I,
    )
    if match_index:
        index = int(match_index.group(1))
        nome = texto[: match_index.start()].strip()

    if not nome:
        raise ValueError("Informe o nome do proprietário antes do índice.")

    return nome, index


def interpretar_data_pericias(texto: str) -> date:
    """Interpreta argumentos de `/pericias` (hoje | ontem | data)."""
    texto = (texto or "").strip().lower()
    if not texto or texto in {"hoje", "today"}:
        return hoje()
    if texto in {"ontem", "yesterday"}:
        return ontem()

    match = re.search(r"(?:data\s*[=:]?\s*)?(.+)$", texto)
    bruto = (match.group(1) if match else texto).strip()
    return parse_data(bruto)


def executar_comando_fotos(
    client: WebClient,
    config: SlackConfig,
    channel_id: str,
    texto_comando: str,
) -> str:
    """Baixa fotos do Idebras, gera PDF e envia no Slack."""
    proprietario, result_index = interpretar_argumentos_fotos(texto_comando)

    sessao_dir = Path(config.diretorio_temporario) / str(uuid.uuid4())
    sessao_dir.mkdir(parents=True, exist_ok=True)

    try:
        zip_path = sessao_dir / "fotos.zip"
        try:
            download_owner_photos(
                proprietario,
                zip_path,
                result_index=result_index,
            )
        except MultiplosResultadosError as erro:
            return str(erro)

        pdf_path = zip_to_pdf(zip_path, sessao_dir, pdf_name="fotos.pdf")
        enviar_arquivos_slack(
            client,
            channel_id,
            [pdf_path, zip_path],
            comentario=f"Fotos do imóvel — *{proprietario}*",
        )
        return (
            f"Fotos baixadas para *{proprietario}*.\n"
            "Arquivos enviados: PDF e ZIP."
        )
    finally:
        shutil.rmtree(sessao_dir, ignore_errors=True)


def executar_comando_pericias(
    client: WebClient,
    config: SlackConfig,
    channel_id: str,
    texto_comando: str,
) -> str:
    """Gera a planilha de perícias finalizadas e envia no Slack."""
    day = interpretar_data_pericias(texto_comando)

    sessao_dir = Path(config.diretorio_temporario) / str(uuid.uuid4())
    sessao_dir.mkdir(parents=True, exist_ok=True)

    try:
        excel_path = gerar_relatorio_pericias(day, output_dir=sessao_dir)
        enviar_arquivos_slack(
            client,
            channel_id,
            [excel_path],
            comentario=(
                f"Perícias finalizadas — *{day.strftime('%d/%m/%Y')}*"
            ),
        )
        return (
            f"Planilha de perícias finalizadas em *{day.strftime('%d/%m/%Y')}* enviada."
        )
    finally:
        shutil.rmtree(sessao_dir, ignore_errors=True)
