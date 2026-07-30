"""Download e upload de arquivos no Slack."""

from __future__ import annotations

import logging
import os
import re
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
) -> None:
    """Envia um ou mais arquivos para o canal ou DM (aceita também user ID U...)."""
    canal = resolver_canal_destino(client, channel_id)
    for indice, caminho in enumerate(caminhos):
        comentario_arquivo = comentario if indice == 0 else ""
        client.files_upload_v2(
            channel=canal,
            file=str(caminho),
            title=caminho.name,
            initial_comment=comentario_arquivo,
        )
        logger.info("Arquivo enviado ao Slack: %s → %s", caminho.name, canal)
