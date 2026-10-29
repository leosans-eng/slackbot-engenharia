"""Frases curtas na conversa direta, equivalentes a alguns slash commands."""

from __future__ import annotations

import re
from dataclasses import dataclass

from bot.handlers import limpar_formatacao_slack

_PREFIXO = (
    r"(?:(?:"
    r"por favor|me manda|me envia|me envie|"
    r"quero|preciso|favor|pode|consegue|"
    r"baixar|baixa|baixe|baixem|"
    r"buscar|busca|busque|"
    r"mande|manda|mandar|envia|envie|enviar|"
    r"ver|v[eê]|"
    r"me|mim"
    r")\s+)*"
)
_PREPOSICAO = r"(?:\s+d(?:as|os|e|a|o))?"

_FOTOS = re.compile(
    rf"^{_PREFIXO}(?:as\s+|os\s+)?fotos?\b{_PREPOSICAO}\s*(.*)$",
    re.IGNORECASE,
)
_PARECER = re.compile(
    rf"^{_PREFIXO}(?:o\s+)?parecer\b(?:\s+t[eé]cnico)?{_PREPOSICAO}\s*(.*)$",
    re.IGNORECASE,
)
_PERICIAS = re.compile(
    rf"^{_PREFIXO}(?:as\s+)?per[ií]cias?\b(?:\s+finalizadas)?(?:\s+de)?\s*(.*)$",
    re.IGNORECASE,
)
_DATA_PERICIA = re.compile(
    r"\b(ontem|hoje|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b",
    re.IGNORECASE,
)
_FOTOS_E_PARECER = re.compile(
    rf"^{_PREFIXO}"
    r"(?:(?:as\s+|os\s+)?fotos?\s+e\s+(?:o\s+)?parecer(?:\s+t[eé]cnico)?"
    r"|(?:o\s+)?parecer(?:\s+t[eé]cnico)?\s+e\s+(?:as\s+|os\s+)?fotos?)"
    rf"{_PREPOSICAO}\s*(.*)$",
    re.IGNORECASE,
)
_COMPLEMENTO = re.compile(
    r"(?:^|\s)(?:"
    r"a[eí]|ai|pfv|pfvr|pf|n[eé]|ne|blz|beleza|vlw|valeu|"
    r"r[aá]pido|rapido|agora|obg|viu|porfa|ok|please"
    r")(?=\s|$)",
    re.IGNORECASE,
)
_REVISAO_BAIXAR = {
    "pode", "consegue", "quero", "preciso", "favor", "vamos", "bora",
    "baixar", "baixa", "baixe", "baixem", "download",
    "as", "os", "das", "dos", "de", "do", "da", "o", "a", "um", "uma",
    "revisao", "revisoes", "parecer", "por", "pra", "para", "me",
    "manda", "mandar", "mim",
    "idebras", "no", "na", "nos", "nas", "em",
}
_REVISAO_FINALIZAR = {
    "pode", "consegue", "quero", "preciso", "favor",
    "finalizar", "finaliza", "finalize",
    "as", "os", "das", "dos", "de", "do", "da", "o", "a", "um", "uma",
    "revisao", "revisoes", "parecer", "por", "pra", "para", "me",
    "idebras", "no", "na", "nos", "nas", "em",
}
_REVISAO_PREVIA_PALAVRAS = {
    "quero", "fazer", "faz", "rodar", "roda", "previa", "completa",
    "a", "o", "as", "os", "da", "de", "do", "das", "revisao", "revisoes",
    "parecer",
}
_SEM_ACENTO = str.maketrans(
    "áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ",
    "aaaaeeioooucAAAAEEIOOOUC",
)


@dataclass(frozen=True)
class PedidoFrase:
    comando: str
    argumento: str


def interpretar_frase(texto: str) -> PedidoFrase | None:
    """Reconhece fotos, parecer, perícias/manifestações ou download da revisão."""
    limpo = _normalizar(texto)
    if not limpo:
        return None

    ambos = _FOTOS_E_PARECER.fullmatch(limpo)
    if ambos and ambos.group(1).strip():
        return PedidoFrase("fotos_parecer", ambos.group(1).strip())

    fotos = _FOTOS.fullmatch(limpo)
    if fotos:
        return PedidoFrase("fotos", fotos.group(1).strip())

    parecer = _PARECER.fullmatch(limpo)
    if parecer:
        return PedidoFrase("parecer", parecer.group(1).strip())

    pericias = _PERICIAS.fullmatch(limpo)
    if pericias:
        return PedidoFrase("pericias", pericias.group(1).strip())

    revisao = _pedido_revisao(limpo)
    if revisao:
        return revisao

    formatar = _pedido_formatar(limpo)
    if formatar:
        return formatar

    prazos = _pedido_prazos(limpo, texto)
    if prazos:
        return prazos

    processo = _pedido_processo(limpo)
    if processo:
        return processo

    return _pedido_pericias_ou_manifestacao(limpo)


def _pedido_revisao(texto: str) -> PedidoFrase | None:
    """Baixa se a frase curta é sobre revisão, mesmo com 'ae' ou 'pode'."""
    if len(texto) > 140:
        return None
    base = _sem_acento(texto).lower()
    if re.search(r"\bnao\b", base) or not re.search(r"\brevis", base):
        return None
    palavras = re.findall(r"[a-z0-9]+", base)
    if not palavras:
        return None
    if "previa" in palavras or "completa" in palavras:
        if all(p in _REVISAO_PREVIA_PALAVRAS for p in palavras):
            return PedidoFrase("revisao", "")
        return None
    if any(p in {"finalizar", "finaliza", "finalize"} for p in palavras):
        if all(p in _REVISAO_FINALIZAR for p in palavras):
            return PedidoFrase("revisao", "finalizar")
        return None
    if all(p in _REVISAO_BAIXAR for p in palavras):
        return PedidoFrase("revisao", "download")
    return None


def _pedido_prazos(limpo: str, original: str) -> PedidoFrase | None:
    """'o que vence hoje' devolve só o resumo, sem a planilha."""
    if len(limpo) > 160:
        return None
    base = _sem_acento(limpo).lower()
    if re.search(r"\bnao\b", base):
        return None
    if re.search(r"\b(?:pericias?|manifestac\w*|laudo|planilha)\b", base):
        return None
    if not re.fullmatch(
        r"(?:(?:"
        r"me diz|me fala|me mostra|mostra|mostrar|quero ver|quero|ver|veja|"
        r"qual|quais"
        r")\s+)*"
        r"(?:"
        r"o que vence|"
        r"o que esta vencid\w*|"
        r"quais(?:\s+os)?\s+prazos?(?:\s+venc\w*)?|"
        r"prazos?(?:\s+vencid\w*)?|"
        r"resumo d(?:e|os|o)\s+prazos?"
        r")"
        r"(?:\s+d(?:e|o|a|os|as))?"
        r"(?:\s+(?:hoje|ontem|amanha|\d{1,2}/\d{1,2}(?:/\d{2,4})?))?",
        base,
    ):
        return None
    datas = _DATA_PERICIA.findall(original)
    if len(datas) > 1:
        return None
    argumento = datas[0] if datas and datas[0].lower() != "hoje" else ""
    return PedidoFrase("prazos", argumento)


def _pedido_processo(texto: str) -> PedidoFrase | None:
    """'processo da Rosangela' consulta prazos e baixa laudo no eproc."""
    if len(texto) > 180:
        return None
    match = re.fullmatch(
        rf"{_PREFIXO}(?:o\s+|os\s+)?processos?\b{_PREPOSICAO}\s*(.*)",
        texto,
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.fullmatch(
            rf"{_PREFIXO}eproc\b{_PREPOSICAO}\s*(.*)",
            texto,
            flags=re.IGNORECASE,
        )
    if not match:
        return None
    return PedidoFrase("processo", match.group(1).strip())


def _pedido_formatar(texto: str) -> PedidoFrase | None:
    """'formata no modelo do perito' escolhe o modelo da planilha já enviada."""
    if len(texto) > 160:
        return None
    base = _sem_acento(texto).lower()
    if re.search(r"\bnao\b", base) or not re.search(r"\bformat", base):
        return None
    if re.search(r"\bperito\b", base) or re.search(r"\bmodelo\s*[=:]?\s*2\b", base):
        return PedidoFrase("formatar", "2")
    if re.search(r"\batualizacao\b", base) or re.search(r"\bmodelo\s*[=:]?\s*1\b", base):
        return PedidoFrase("formatar", "1")
    if re.search(r"\bparecer\s+inicial\b", base) or re.search(
        r"\bmodelo\s*[=:]?\s*3\b", base
    ):
        return PedidoFrase("formatar", "3")
    return PedidoFrase("formatar", "")


def _pedido_pericias_ou_manifestacao(texto: str) -> PedidoFrase | None:
    """'teve perícia ontem?' e 'gera manifestação' viram o relatório de perícias."""
    if len(texto) > 160:
        return None
    base = _sem_acento(texto).lower()
    if not re.search(r"\b(?:pericias?|manifestacao|manifestacoes)\b", base):
        return None
    datas = _DATA_PERICIA.findall(texto)
    if len(datas) > 1:
        return None
    return PedidoFrase("pericias", datas[0] if datas else "")


def _sem_acento(texto: str) -> str:
    return texto.translate(_SEM_ACENTO)


def _normalizar(texto: str) -> str:
    texto = limpar_formatacao_slack(texto or "")
    texto = re.sub(r"<@[^>]+>", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    texto = re.sub(r"\s*,?\s*por favor$", "", texto, flags=re.IGNORECASE).strip()
    texto = re.sub(r"[?!.,;:]+$", "", texto).strip()
    anterior = None
    while anterior != texto:
        anterior = texto
        texto = _COMPLEMENTO.sub(" ", texto)
        texto = re.sub(r"\s+", " ", texto).strip()
    return texto
