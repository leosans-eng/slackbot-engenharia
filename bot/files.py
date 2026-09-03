"""Download e upload de arquivos no Slack."""

from __future__ import annotations

import logging
import os
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

from slack_sdk import WebClient

logger = logging.getLogger(__name__)

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# Canal válido para files_upload_v2: C/G/D/Z + alfanumérico
CANAL_UPLOAD_RE = re.compile(r"^[CGDZ][A-Z0-9]{8,}$")
USER_ID_RE = re.compile(r"^U[A-Z0-9]{8,}$")
MENTION_USER_RE = re.compile(r"^<@(U[A-Z0-9]+)>$")


def eh_planilha_xlsx(arquivo: dict) -> bool:
    nome = (arquivo.get("name") or "").lower()
    mimetype = (arquivo.get("mimetype") or "").lower()
    return nome.endswith(".xlsx") or mimetype == MIME_XLSX


def _sanitizar_nome_arquivo(nome: str) -> str:
    nome_limpo = re.sub(r'[<>:"/\\|?*]', "-", nome)
    return re.sub(r"\s+", " ", nome_limpo).strip() or "planilha.xlsx"


def eh_erro_rede_transiente(erro: BaseException) -> bool:
    if isinstance(erro, urllib.error.HTTPError):
        try:
            return 500 <= int(erro.code) < 600
        except (TypeError, ValueError):
            return False
    texto = str(erro).lower()
    if any(
        trecho in texto
        for trecho in (
            "getaddrinfo",
            "11002",
            "timed out",
            "timeout",
            "temporarily",
            "connection reset",
            "connection aborted",
            "10054",
            "10060",
            "name or service not known",
        )
    ):
        return True
    if isinstance(erro, (TimeoutError, socket.timeout, socket.gaierror)):
        return True
    causa = getattr(erro, "reason", None) or erro.__cause__
    if causa is None or causa is erro or not isinstance(causa, BaseException):
        return False
    return eh_erro_rede_transiente(causa)


def descrever_erro_envio(erro: BaseException) -> str:
    """Texto curto para a mensagem no Slack, sem esconder a causa real."""
    detalhe = str(erro).strip() or type(erro).__name__
    if len(detalhe) > 400:
        detalhe = detalhe[:400] + "…"
    extra = ""
    baixo = detalhe.lower()
    if "getaddrinfo" in baixo or "11002" in baixo:
        extra = (
            "A geração no Idebras pode ter concluído; a falha foi na "
            "*rede ao enviar o arquivo ao Slack* (DNS).\n\n"
        )
    elif eh_erro_rede_transiente(erro):
        extra = "Falha de rede ao falar com o Slack.\n\n"
    return f"{extra}*Detalhe:* `{detalhe}`"


def resolver_canal_destino(client: WebClient, destino: str) -> str:
    """
    Resolve canal/user ID para um channel_id aceito pelo files_upload_v2.

    - C/G/D/Z... → usa direto
    - U... → abre DM e retorna o canal D...
    """
    destino = (destino or "").strip()
    if not destino:
        raise ValueError("Destino Slack vazio.")

    mention = MENTION_USER_RE.match(destino)
    if mention:
        destino = mention.group(1)

    if CANAL_UPLOAD_RE.match(destino):
        return destino

    if USER_ID_RE.match(destino):
        resposta = client.conversations_open(users=destino)
        canal = (resposta.get("channel") or {}).get("id")
        if not canal:
            raise ValueError(
                f"Não foi possível abrir DM com o usuário `{destino}`."
            )
        logger.info("DM aberta: user=%s → canal=%s", destino, canal)
        return canal

    raise ValueError(
        f"Destino Slack inválido: `{destino}`. "
        "Use ID de canal (C...), grupo (G...), DM (D...) ou usuário (U...)."
    )


def baixar_arquivo_slack(
    client: WebClient,
    file_id: str,
    nome_arquivo: str,
    diretorio_destino: str,
) -> Path:
    """Baixa um arquivo privado do Slack para o diretório indicado."""
    resposta = client.files_info(file=file_id)
    arquivo = resposta.get("file")
    if not arquivo:
        raise FileNotFoundError(f"Arquivo Slack não encontrado: {file_id}")

    url = arquivo.get("url_private_download") or arquivo.get("url_private")
    if not url:
        raise ValueError(f"Slack não retornou URL de download para '{nome_arquivo}'.")

    os.makedirs(diretorio_destino, exist_ok=True)
    destino = Path(diretorio_destino) / _sanitizar_nome_arquivo(nome_arquivo)

    token = client.token
    if not token:
        raise ValueError("Token do bot não disponível para download.")

    requisicao = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(requisicao) as resposta_http:
            destino.write_bytes(resposta_http.read())
    except urllib.error.HTTPError as erro:
        raise OSError(f"Falha ao baixar '{nome_arquivo}' do Slack: HTTP {erro.code}") from erro

    logger.info("Arquivo baixado: %s", destino)
    return destino


def enviar_arquivos_slack(
    client: WebClient,
    channel_id: str,
    caminhos: list[Path],
    comentario: str = "",
    *,
    tentativas: int = 3,
) -> None:
    """Envia um ou mais arquivos para o canal ou DM (aceita também user ID U...)."""
    canal = resolver_canal_destino(client, channel_id)
    for indice, caminho in enumerate(caminhos):
        comentario_arquivo = comentario if indice == 0 else ""
        ultimo_erro: BaseException | None = None
        for tentativa in range(1, tentativas + 1):
            try:
                client.files_upload_v2(
                    channel=canal,
                    file=str(caminho),
                    title=caminho.name,
                    initial_comment=comentario_arquivo,
                )
                ultimo_erro = None
                break
            except Exception as exc:
                ultimo_erro = exc
                if tentativa >= tentativas or not eh_erro_rede_transiente(exc):
                    break
                espera = 2**tentativa
                logger.warning(
                    "Envio de %s ao Slack falhou (%s). Tentativa %s/%s em %ss.",
                    caminho.name,
                    exc,
                    tentativa,
                    tentativas,
                    espera,
                )
                time.sleep(espera)
        if ultimo_erro is not None:
            raise RuntimeError(
                f"Falha ao enviar `{caminho.name}` ao Slack: {ultimo_erro}"
            ) from ultimo_erro
        logger.info("Arquivo enviado ao Slack: %s → %s", caminho.name, canal)


def enviar_arquivos_para_destinos(
    client: WebClient,
    destinos: list[str],
    caminhos: list[Path],
    comentario: str = "",
) -> list[str]:
    """Envia os mesmos arquivos para vários canais/usuários. Retorna canais resolvidos."""
    enviados: list[str] = []
    falhas: list[str] = []
    for destino in destinos:
        try:
            enviar_arquivos_slack(client, destino, caminhos, comentario=comentario)
            enviados.append(destino)
        except Exception as exc:
            logger.exception("Falha ao enviar arquivos para %s", destino)
            falhas.append(f"{destino}: {exc}")
    if falhas:
        extra = (
            f" Enviado para {len(enviados)} destino(s)." if enviados else ""
        )
        raise RuntimeError(
            "Falha ao enviar o arquivo no Slack." + extra + " " + " | ".join(falhas)
        )
    return enviados


def resolver_canal_comando(
    client: WebClient,
    channel_id: str,
    user_id: str,
) -> str:
    """Resolve canal do slash command; se falhar, abre DM com o usuário."""
    for candidato in (channel_id, user_id):
        if not candidato:
            continue
        try:
            return resolver_canal_destino(client, candidato)
        except Exception as erro:
            logger.warning("Não resolveu destino %s: %s", candidato, erro)
    raise ValueError(
        "Não foi possível resolver o canal para envio. "
        "Abra uma DM com o bot e tente de novo."
    )
