"""Lógica de negócio do bot Slack."""

from __future__ import annotations

import logging
import os
import re
import shutil
import uuid
from pathlib import Path

from slack_sdk import WebClient

from formatador import Modelo, formatar_planilha
from formatador.types import ResultadoFormatacao
from slack_bot.config import SlackConfig
from slack_bot.files import baixar_arquivo_slack, enviar_arquivos_slack
from slack_bot.state import ArquivoPendente, obter_planilha_pendente, registrar_planilha
from slack_bot.usuarios import rotulo_usuario

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
        from slack_bot.files import eh_planilha_xlsx

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
        os.environ.get("FORMATADOR_TEMP_DIR", os.path.join(os.getcwd(), "tmp", "slack")),
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
