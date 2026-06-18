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


def eh_planilha_xlsx(arquivo: dict) -> bool:
    nome = (arquivo.get("name") or "").lower()
    mimetype = (arquivo.get("mimetype") or "").lower()
    return nome.endswith(".xlsx") or mimetype == MIME_XLSX


def _sanitizar_nome_arquivo(nome: str) -> str:
    nome_limpo = re.sub(r'[<>:"/\\|?*]', "-", nome)
    return re.sub(r"\s+", " ", nome_limpo).strip() or "planilha.xlsx"


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
    """Envia um ou mais arquivos para o canal ou DM."""
    for indice, caminho in enumerate(caminhos):
        comentario_arquivo = comentario if indice == 0 else ""
        client.files_upload_v2(
            channel=channel_id,
            file=str(caminho),
            title=caminho.name,
            initial_comment=comentario_arquivo,
        )
        logger.info("Arquivo enviado ao Slack: %s", caminho.name)
