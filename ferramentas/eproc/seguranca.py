"""Trava de somente leitura: consulta e download. Nenhum peticionamento."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

_HOSTS_EPROC = ("eproc.jfrj.jus.br",)
_HOSTS_CAPTCHA = ("challenges.cloudflare.com",)

# Qualquer ação com um destes trechos é movimento de escrita e deve ser bloqueada.
_ESCRITA = (
    "peticion",
    "protocol",
    "moviment",
    "juntar",
    "ajuiz",
    "excluir",
    "substabelec",
    "desativ",
    "senha_alterar",
    "pessoa_alterar",
    "processo_cadastrar",
    "lembrete_externo_cadastrar",
    "lembrete_cadastrar",
    "assinar",
    "minuta_imprimir",
    "incluir_documento",
    "salvar",
    "cancelar_moviment",
    "dispositivo_liberado_cancelar",
)

_POST_PERMITIDO = (
    "processo_pesquisa_rapida",
)


def acao_da_url(url: str) -> str:
    consulta = parse_qs(urlparse(url).query)
    for chave in ("acao", "acao_ajax"):
        valores = consulta.get(chave)
        if valores and valores[0]:
            return valores[0]
    return ""


def acao_de_escrita(acao: str) -> bool:
    texto = (acao or "").lower()
    return any(trecho in texto for trecho in _ESCRITA)


def host_permitido(url: str, host_2fa: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host in _HOSTS_EPROC or host in _HOSTS_CAPTCHA:
        return True
    if host_2fa and host == host_2fa:
        return True
    return False


def post_permitido(url: str, host_2fa: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    caminho = (urlparse(url).path or "").lower()
    if host in _HOSTS_CAPTCHA:
        return True
    if host_2fa and host == host_2fa:
        return True
    if host not in _HOSTS_EPROC:
        return False
    if caminho.endswith("/index.php") or caminho.endswith("/eproc/index.php"):
        return True
    if caminho.rstrip("/").endswith("/eproc"):
        return True
    acao = acao_da_url(url).lower()
    return acao in _POST_PERMITIDO


def href_documento(href: str) -> bool:
    """Link de download de documento já juntado, sem ação de escrita."""
    acao = acao_da_url(href).lower()
    if acao_de_escrita(acao):
        return False
    return acao in {
        "acessar_documento",
        "acessar_documento_implementacao",
        "exibir_documento",
    }
