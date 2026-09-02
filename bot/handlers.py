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
    download_owner_parecer,
    download_owner_photos,
    finalizar_revisoes_parecer,
    gerar_relatorio_fluxos_cp,
    gerar_relatorio_pericias,
    hoje,
    ontem,
    parse_data,
    zip_to_pdf,
)
from ferramentas.idebras.revisao_parecer import gravar_log_download_horario
from bot.config import SlackConfig
from bot.files import (
    baixar_arquivo_slack,
    enviar_arquivos_para_destinos,
    enviar_arquivos_slack,
    resolver_canal_comando,
    resolver_canal_destino,
)
from bot.state import (
    ArquivoPendente,
    obter_planilha_pendente,
    obter_revisao_pendente,
    registrar_planilha,
    registrar_revisao_pendente,
    remover_revisao_pendente,
)
from bot.status_msg import ProgressCallback, progress_noop
from bot.usuarios import rotulo_usuario
from ferramentas.idebras.config import REVISAO_PARECER_DIR, parse_destinos_slack

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


def interpretar_argumentos_imovel(texto: str, *, comando: str = "fotos") -> tuple[str, int | None]:
    """Extrai nome do proprietário e índice opcional (`/fotos`, `/parecer`)."""
    texto = (texto or "").strip()
    if not texto:
        raise ValueError(
            "Informe o nome do proprietário.\n"
            "Exemplos:\n"
            f"`/{comando} João da Silva`\n"
            f"`/{comando} João da Silva opcao=2`"
        )

    index: int | None = None
    nome = texto

    match_index = re.search(
        r"(?:^|\s)(?:opcao|opção)\s*[=:]?\s*(\d+)\s*$",
        texto,
        flags=re.I,
    )
    if match_index:
        index = int(match_index.group(1))
        nome = texto[: match_index.start()].strip()
    else:
        # Aceita "/fotos Nome 5" (ou /parecer) como atalho de opcao=5
        match_trailing = re.search(r"^(.*?)\s+(\d+)\s*$", texto)
        if match_trailing and match_trailing.group(1).strip():
            nome = match_trailing.group(1).strip()
            index = int(match_trailing.group(2))

    if not nome:
        raise ValueError("Informe o nome do proprietário antes da opção.")

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
    *,
    user_id: str = "",
    on_progress: ProgressCallback | None = None,
) -> str:
    """Baixa fotos do Idebras, gera PDF e envia no Slack."""
    progress = on_progress or progress_noop
    proprietario, result_index = interpretar_argumentos_imovel(
        texto_comando, comando="fotos"
    )
    canal = resolver_canal_comando(client, channel_id, user_id)

    sessao_dir = Path(config.diretorio_temporario) / str(uuid.uuid4())
    sessao_dir.mkdir(parents=True, exist_ok=True)

    try:
        zip_path = sessao_dir / "fotos.zip"
        try:
            download_owner_photos(
                proprietario,
                zip_path,
                result_index=result_index,
                on_progress=progress,
            )
        except MultiplosResultadosError as erro:
            return str(erro)

        progress("Gerando PDF…")
        pdf_path = zip_to_pdf(zip_path, sessao_dir, pdf_name="fotos.pdf")

        progress("Enviando PDF…")
        enviar_arquivos_slack(client, canal, [pdf_path], comentario="")
        progress("Enviando ZIP…")
        enviar_arquivos_slack(client, canal, [zip_path], comentario="")

        return (
            f"Fotos baixadas para *{proprietario}*.\n"
            "Arquivos enviados: PDF e ZIP."
        )
    finally:
        shutil.rmtree(sessao_dir, ignore_errors=True)


def executar_comando_parecer(
    client: WebClient,
    config: SlackConfig,
    channel_id: str,
    texto_comando: str,
    *,
    user_id: str = "",
    on_progress: ProgressCallback | None = None,
) -> str:
    """Baixa o Parecer Técnico do Idebras e envia o PDF no Slack."""
    progress = on_progress or progress_noop
    proprietario, result_index = interpretar_argumentos_imovel(
        texto_comando, comando="parecer"
    )
    canal = resolver_canal_comando(client, channel_id, user_id)

    sessao_dir = Path(config.diretorio_temporario) / str(uuid.uuid4())
    sessao_dir.mkdir(parents=True, exist_ok=True)

    try:
        pdf_path = sessao_dir / "parecer.pdf"
        try:
            pdf_path = download_owner_parecer(
                proprietario,
                pdf_path,
                result_index=result_index,
                on_progress=progress,
            )
        except MultiplosResultadosError as erro:
            return str(erro)

        progress("Enviando PDF…")
        enviar_arquivos_slack(client, canal, [pdf_path], comentario="")
        return f"Parecer técnico de *{proprietario}* enviado."
    finally:
        shutil.rmtree(sessao_dir, ignore_errors=True)


def executar_comando_pericias(
    client: WebClient,
    config: SlackConfig,
    channel_id: str,
    texto_comando: str,
    *,
    user_id: str = "",
) -> str:
    """Gera a planilha de perícias finalizadas e envia no Slack.

    Raises:
        SemPericiasError: sem registros na data (agendamento deve ignorar).
    """
    day = interpretar_data_pericias(texto_comando)

    sessao_dir = Path(config.diretorio_temporario) / str(uuid.uuid4())
    sessao_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Gera antes de abrir DM — se estiver vazio, não notifica ninguém
        excel_path = gerar_relatorio_pericias(day, output_dir=sessao_dir)

        destinos = parse_destinos_slack(channel_id)
        if len(destinos) <= 1:
            unico = destinos[0] if destinos else channel_id
            destinos = [resolver_canal_comando(client, unico, user_id)]

        enviar_arquivos_para_destinos(
            client,
            destinos,
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


def executar_fluxos_cp(
    client: WebClient,
    config: SlackConfig,
    channel_id: str,
    *,
    user_id: str = "",
    close_app: bool = True,
) -> str:
    """Abre o Infobase, exporta, formata e envia no Slack (um ou vários destinos)."""
    destinos = parse_destinos_slack(channel_id)
    if len(destinos) <= 1:
        unico = destinos[0] if destinos else channel_id
        destinos = [resolver_canal_comando(client, unico, user_id)]

    sessao_dir = Path(config.diretorio_temporario) / str(uuid.uuid4())
    sessao_dir.mkdir(parents=True, exist_ok=True)

    try:
        excel_path = gerar_relatorio_fluxos_cp(
            output_dir=sessao_dir,
            close_app=close_app,
        )
        enviar_arquivos_para_destinos(
            client,
            destinos,
            [excel_path],
            comentario="Fluxos CP — relatório diário",
        )
        if len(destinos) == 1:
            return "Planilha de fluxos CP enviada."
        return f"Planilha de fluxos CP enviada para {len(destinos)} destinatários."
    finally:
        shutil.rmtree(sessao_dir, ignore_errors=True)


def interpretar_modo_revisao(texto: str) -> str:
    """Interpreta o argumento de `/revisao`."""
    t = (texto or "").strip().lower()
    if t in {"", "completo", "preview", "prévia", "previa"}:
        return "preview"
    if t in {"confirmar", "confirm", "enviar", "--confirmar"}:
        return "confirmar"
    if t in {"cancelar", "cancela", "não", "nao"}:
        return "cancelar"
    if t in {"finalizar", "finaliza", "envio"}:
        return "finalizar"
    if t in {"download", "baixar", "word", "words"}:
        return "download"
    raise ValueError(
        f"Argumento inválido: `{texto}`. Use `/revisao`, `/revisao download` "
        "ou `/revisao finalizar`. Depois da prévia, responda *sim* para finalizar "
        "ou *não* / *cancelar* para descartar."
    )


def texto_parece_confirmacao_revisao(texto: str) -> bool:
    t = re.sub(r"<@[^>]+>", "", texto or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t in {"sim", "confirmar", "confirm", "yes"}


def texto_parece_cancelamento_revisao(texto: str) -> bool:
    t = re.sub(r"<@[^>]+>", "", texto or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t in {"não", "nao", "cancelar", "cancel", "no"}


def _executar_revisao_isolada(modo: str) -> dict:
    from bot.isolamento import (
        TIMEOUT_COMANDO_REVISAO,
        alvo_finalizar_revisao,
        rodar_processo_resultado,
    )

    return rodar_processo_resultado(
        alvo_finalizar_revisao,
        (modo,),
        timeout=TIMEOUT_COMANDO_REVISAO,
        nome=f"revisao-{modo}",
    )


def _confirmar_revisao_pendente(
    user_id: str,
    channel_id: str,
    *,
    on_progress: ProgressCallback | None = None,
) -> str:
    pendente = obter_revisao_pendente(user_id, channel_id)
    if not pendente:
        return (
            "Não há uma prévia de `/revisao` aguardando confirmação neste canal. "
            "Rode `/revisao` e depois responda *sim* ou *confirmar*."
        )
    remover_revisao_pendente(user_id, channel_id)
    if on_progress:
        on_progress("Finalizando revisões do parecer no Idebras…")
    dados = _executar_revisao_isolada("finalizar")
    return dados["mensagem"]


def executar_confirmacao_revisao(
    user_id: str,
    channel_id: str,
    *,
    on_progress: ProgressCallback | None = None,
) -> str:
    return _confirmar_revisao_pendente(
        user_id, channel_id, on_progress=on_progress
    )


def executar_cancelamento_revisao(user_id: str, channel_id: str) -> str:
    pendente = obter_revisao_pendente(user_id, channel_id)
    if not pendente:
        return (
            "Não há uma prévia de `/revisao` aguardando confirmação neste canal."
        )
    remover_revisao_pendente(user_id, channel_id)
    return "Prévia descartada. Nenhum parecer foi finalizado."


def executar_comando_revisao(
    client: WebClient,
    config: SlackConfig,
    channel_id: str,
    texto_comando: str,
    *,
    user_id: str = "",
    on_progress: ProgressCallback | None = None,
) -> str:
    """Prévia, download, finalização imediata ou confirmação da revisão."""
    progress = on_progress or progress_noop
    modo = interpretar_modo_revisao(texto_comando)

    if modo == "confirmar":
        return _confirmar_revisao_pendente(
            user_id, channel_id, on_progress=progress
        )

    if modo == "cancelar":
        return executar_cancelamento_revisao(user_id, channel_id)

    if on_progress:
        if modo == "download":
            on_progress("Baixando Words automáticos para a pasta Bot…")
        elif modo == "finalizar":
            on_progress("Finalizando revisões do parecer no Idebras…")
        else:
            on_progress("Conferindo revisões do parecer…")

    dados = _executar_revisao_isolada(modo)
    if modo == "preview":
        if dados["a_finalizar"]:
            registrar_revisao_pendente(user_id, channel_id)
        else:
            remover_revisao_pendente(user_id, channel_id)
    return dados["mensagem"]


def executar_download_revisao_agendado(client: WebClient, destinos: list[str]) -> None:
    """Baixa Words faltantes para a pasta Bot e avisa só se houver novidade ou falha."""
    resultado = finalizar_revisoes_parecer(modo="download", gravar_log=False)
    gravou = gravar_log_download_horario(REVISAO_PARECER_DIR, resultado)
    if not gravou:
        return
    if not resultado.tem_word_novo() and not resultado.falhas:
        logger.info("Download horário da revisão: nenhum Word novo.")
        return
    texto = resultado.mensagem_slack()
    if len(texto) > 3500:
        texto = texto[:3490] + "\n…"
    for destino in destinos:
        canal = resolver_canal_destino(client, destino)
        client.chat_postMessage(channel=canal, text=texto)
