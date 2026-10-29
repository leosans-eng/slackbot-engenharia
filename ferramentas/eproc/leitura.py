"""Interpreta a página do processo e monta o resumo. Não acessa a rede."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from lxml import html as html_lib

from ferramentas.eproc.seguranca import href_documento

_CNJ = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")
_SEM_ACENTO = str.maketrans(
    "áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ",
    "aaaaeeioooucAAAAEEIOOOUC",
)
_PARTES_AUTOR = {
    "AUTOR",
    "EXEQUENTE",
    "REQUERENTE",
    "EMBARGANTE",
    "AGRAVANTE",
    "APELANTE",
    "IMPETRANTE",
}
_PARTES_REU = {
    "REU",
    "EXECUTADO",
    "REQUERIDO",
    "RECLAMADO",
    "IMPETRADO",
    "EMBARGADO",
    "APELADO",
    "AGRAVADO",
}
_IGNORAR_NOME = {
    "de", "da", "do", "das", "dos", "e", "o", "a", "os", "as",
    "na", "no", "nos", "nas", "em",
}


class ConsultaInterrompida(RuntimeError):
    """O eproc mostrou uma tela fora da consulta. Nada deve ser movimentado."""


@dataclass(frozen=True)
class Alvo:
    nome: str
    numero: str
    vara: str = ""


@dataclass(frozen=True)
class PedidoConsulta:
    nome: str
    numero: str | None
    completo: bool


@dataclass(frozen=True)
class TribunalCNJ:
    sigla: str
    nome: str
    unidade: str

    @property
    def texto(self) -> str:
        return f"{self.nome} ({self.sigla}), unidade {self.unidade}"


@dataclass
class Documento:
    rotulo: str
    href: str


@dataclass
class Evento:
    numero: int
    data: str
    rotulo: str
    descricao: str
    documentos: list[Documento] = field(default_factory=list)

    @property
    def eh_laudo(self) -> bool:
        return "LAUDO PERICIAL" in _sem_acento(self.rotulo).upper()

    @property
    def eh_decisao(self) -> bool:
        rotulo = _sem_acento(self.rotulo).upper()
        if "CONCLUS" in rotulo or "CANCELAD" in rotulo:
            return False
        return "DECISAO" in rotulo or "DESPACHO" in rotulo


@dataclass
class Prazo:
    evento: int
    parte: str
    parte_nome: str
    dias: str
    status: str
    inicio: str
    final: str
    referido: int | None

    @property
    def eh_autor(self) -> bool:
        return self.parte in _PARTES_AUTOR

    @property
    def em_aberto(self) -> bool:
        status = _sem_acento(self.status).upper()
        if "FECHAD" in status or "CANCEL" in status:
            return False
        return "ABERT" in status or "AGUARD" in status


@dataclass
class LeituraProcesso:
    numero: str
    autor_pagina: str
    reus: list[str]
    peritos: list[str]
    prazos: list[Prazo]
    laudo: Evento | None
    despacho: Evento | None
    outros_laudos: int


def resolver_pedido(texto: str) -> PedidoConsulta:
    """Nome ou número CNJ. `completo` pede o processo na íntegra."""
    original = re.sub(r"\s+", " ", (texto or "").strip())
    if not original or _sem_acento(original).casefold() in {"todos", "trf2", "eproc"}:
        raise ValueError(
            "Informe o nome ou o número CNJ. "
            "Ex.: `/processo Maria da Silva`."
        )
    completo = bool(re.search(r"\b(?:completo|integra)\b", _sem_acento(original), flags=re.I))
    limpo = re.sub(r"(?i)\b(?:completo|integra|íntegra|download)\b", " ", original)
    limpo = re.sub(r"\s+", " ", limpo).strip()
    anterior = None
    while anterior != limpo:
        anterior = limpo
        limpo = re.sub(
            r"(?i)^(na|no|nos|nas|em|de|do|da|dos|das|para|pra|pro)\s+",
            "",
            limpo,
        ).strip()
    numero = extrair_cnj(limpo)
    nome = _CNJ.sub(" ", limpo) if numero else limpo
    nome = re.sub(r"\s+", " ", nome).strip()
    if not numero and not _palavras_nome(nome):
        raise ValueError(
            "Informe o nome ou o número CNJ. "
            "Ex.: `/processo Maria da Silva`."
        )
    return PedidoConsulta(nome=nome, numero=numero, completo=completo)


def _palavras_nome(texto: str) -> list[str]:
    consulta = _sem_acento(texto).casefold()
    return [p for p in re.findall(r"[a-z0-9]+", consulta) if p not in _IGNORAR_NOME]


def tribunal_do_cnj(numero: str) -> TribunalCNJ | None:
    """Justiça, tribunal e unidade de origem, no formato do CNJ."""
    match = re.fullmatch(r"\d{7}-\d{2}\.\d{4}\.(\d)\.(\d{2})\.(\d{4})", numero or "")
    if not match:
        return None
    justica, tribunal, unidade = match.group(1), match.group(2), match.group(3)
    sigla, nome = _tribunal_cnj(justica, tribunal)
    return TribunalCNJ(sigla=sigla, nome=nome, unidade=unidade)


def consulta_disponivel(numero: str) -> bool:
    """Sistema de consulta já ligado para esse número. Hoje, o eproc do TRF2."""
    tribunal = tribunal_do_cnj(numero)
    return tribunal is not None and tribunal.sigla == "TRF2"


def mensagem_sem_consulta(numero: str, nome: str = "") -> str:
    tribunal = tribunal_do_cnj(numero)
    quem = f"*{nome}*\n" if nome else ""
    if tribunal is None:
        return f"{quem}`{numero}`\nNão identifiquei o tribunal nesse número."
    return (
        f"{quem}`{numero}`\n{tribunal.texto}\n"
        "A consulta nesse tribunal ainda não está ligada."
    )


_UF = {
    "01": ("AC", "Acre"),
    "02": ("AL", "Alagoas"),
    "03": ("AP", "Amapá"),
    "04": ("AM", "Amazonas"),
    "05": ("BA", "Bahia"),
    "06": ("CE", "Ceará"),
    "07": ("DF", "Distrito Federal"),
    "08": ("ES", "Espírito Santo"),
    "09": ("GO", "Goiás"),
    "10": ("MA", "Maranhão"),
    "11": ("MT", "Mato Grosso"),
    "12": ("MS", "Mato Grosso do Sul"),
    "13": ("MG", "Minas Gerais"),
    "14": ("PA", "Pará"),
    "15": ("PB", "Paraíba"),
    "16": ("PR", "Paraná"),
    "17": ("PE", "Pernambuco"),
    "18": ("PI", "Piauí"),
    "19": ("RJ", "Rio de Janeiro"),
    "20": ("RN", "Rio Grande do Norte"),
    "21": ("RS", "Rio Grande do Sul"),
    "22": ("RO", "Rondônia"),
    "23": ("RR", "Roraima"),
    "24": ("SC", "Santa Catarina"),
    "25": ("SE", "Sergipe"),
    "26": ("SP", "São Paulo"),
    "27": ("TO", "Tocantins"),
}


def _ordinal(codigo: str) -> str:
    return f"{int(codigo)}ª"


def _uf(codigo: str) -> tuple[str, str] | None:
    return _UF.get(codigo)


def _tribunal_cnj(justica: str, tribunal: str) -> tuple[str, str]:
    if justica == "1":
        return "STF", "Supremo Tribunal Federal"
    if justica == "2":
        return "CNJ", "Conselho Nacional de Justiça"
    if justica == "3":
        return "STJ", "Superior Tribunal de Justiça"
    if justica == "4":
        if tribunal in {f"{n:02d}" for n in range(1, 7)}:
            ordem = _ordinal(tribunal)
            return f"TRF{int(tribunal)}", f"Tribunal Regional Federal da {ordem} Região"
        return "JF", "Justiça Federal"
    if justica == "5":
        if tribunal in {f"{n:02d}" for n in range(1, 25)}:
            ordem = _ordinal(tribunal)
            return f"TRT{int(tribunal)}", f"Tribunal Regional do Trabalho da {ordem} Região"
        return "JT", "Justiça do Trabalho"
    if justica == "6":
        if tribunal == "00":
            return "TSE", "Tribunal Superior Eleitoral"
        estado = _uf(tribunal)
        if estado:
            return f"TRE-{estado[0]}", f"Tribunal Regional Eleitoral de {estado[1]}"
        return "JE", "Justiça Eleitoral"
    if justica == "7":
        if tribunal == "00":
            return "STM", "Superior Tribunal Militar"
        return "JMU", "Justiça Militar da União"
    if justica == "8":
        estado = _uf(tribunal)
        if estado:
            sigla = "TJDFT" if estado[0] == "DF" else f"TJ{estado[0]}"
            return sigla, f"Tribunal de Justiça de {estado[1]}"
        return "TJ", "Tribunal de Justiça"
    if justica == "9":
        estado = _uf(tribunal)
        if estado:
            return f"TJM{estado[0]}", f"Tribunal de Justiça Militar de {estado[1]}"
        return "JME", "Justiça Militar Estadual"
    return "CNJ", "Tribunal indicado no número CNJ"


def extrair_cnj(texto: str) -> str | None:
    match = _CNJ.search(texto or "")
    if match:
        return match.group(0)
    digitos = re.sub(r"\D", "", texto or "")
    if len(digitos) != 20:
        return None
    return (
        f"{digitos[0:7]}-{digitos[7:9]}.{digitos[9:13]}."
        f"{digitos[13]}.{digitos[14:16]}.{digitos[16:20]}"
    )


def ler_processo(conteudo: str, numero: str) -> LeituraProcesso:
    documento = html_lib.fromstring(conteudo)
    eventos = _eventos(documento)
    prazos = _prazos(documento)
    laudos = [evento for evento in eventos if evento.eh_laudo and evento.documentos]
    laudo = max(laudos, key=lambda evento: evento.numero) if laudos else None
    despacho = _escolher_despacho(eventos, prazos)
    reus, peritos = _partes_da_pagina(documento)
    return LeituraProcesso(
        numero=numero,
        autor_pagina=_autor_da_pagina(documento),
        reus=reus,
        peritos=peritos,
        prazos=_prazos_relevantes(prazos),
        laudo=laudo,
        despacho=despacho,
        outros_laudos=max(0, len(laudos) - 1),
    )


def mensagem_processo(nome: str, leitura: LeituraProcesso, *, vara: str = "") -> str:
    titulo = (nome.strip() or leitura.autor_pagina or "Processo").title()
    linhas = [f"*{titulo}*", leitura.numero]
    tribunal = tribunal_do_cnj(leitura.numero)
    if tribunal:
        linhas.append(tribunal.texto)
    if vara.strip():
        linhas.append(f"Vara no Idebras: {vara.strip()}")
    autor = leitura.autor_pagina
    if autor and autor.casefold() not in titulo.casefold():
        linhas.append(f"Autor no processo: {autor}")
    if leitura.reus:
        linhas.extend(["", "*Réu*" if len(leitura.reus) == 1 else "*Réus*"])
        linhas.extend(f"• {nome}" for nome in leitura.reus)
    if leitura.peritos:
        linhas.extend(["", "*Perito*" if len(leitura.peritos) == 1 else "*Peritos*"])
        linhas.extend(f"• {nome}" for nome in leitura.peritos)
    linhas.extend(["", "*Prazo do autor*"])
    do_autor = [prazo for prazo in leitura.prazos if prazo.eh_autor]
    if do_autor:
        linhas.extend(_linha_prazo(prazo) for prazo in do_autor)
    else:
        linhas.append("Nenhum prazo do autor nesta página.")

    outros = [prazo for prazo in leitura.prazos if not prazo.eh_autor]
    linhas.extend(["", "*Outros prazos*"])
    if outros:
        linhas.extend(_linha_prazo(prazo) for prazo in outros)
    else:
        linhas.append("Nenhum.")

    linhas.extend(["", "*Laudo pericial*"])
    if leitura.laudo:
        extra = " (o mais recente)" if leitura.outros_laudos else ""
        linhas.append(
            f"Evento {leitura.laudo.numero} — {leitura.laudo.data} — "
            f"{leitura.laudo.rotulo}{extra}"
        )
    else:
        linhas.append("Não encontrei laudo pericial com documento.")

    linhas.extend(["", "*Despacho decisivo*"])
    if leitura.despacho:
        linhas.append(
            f"Evento {leitura.despacho.numero} — {leitura.despacho.data} — "
            f"{leitura.despacho.rotulo}"
        )
    else:
        linhas.append("Não encontrei decisão ou despacho com documento ligado ao prazo.")

    return "\n".join(linhas)


def nome_arquivo_zip(nome: str, sugerido: str) -> str:
    base = _nome_seguro(nome)
    extensao = Path(sugerido).suffix.lower()
    if extensao not in {".zip", ".pdf"}:
        extensao = ".zip"
    return f"completo_{base}{extensao}"


def nome_arquivo(prefixo: str, nome: str, indice: int, total: int) -> str:
    base = _nome_seguro(nome)
    sufixo = f"_{indice}" if total > 1 else ""
    return f"{prefixo}_{base}{sufixo}.pdf"


def _nome_seguro(nome: str) -> str:
    base = re.sub(r'[<>:"/\\|?*]+', "", nome.strip())
    base = re.sub(r"\s+", "_", base)
    base = re.sub(r"_+", "_", base).strip("._") or "processo"
    if len(base) > 60:
        base = base[:60].rstrip("._")
    return base


def _prazos_relevantes(prazos: list[Prazo]) -> list[Prazo]:
    """Prazo mais recente do autor e os que ainda estão abertos."""
    abertos = [prazo for prazo in prazos if prazo.em_aberto]
    autores = [prazo for prazo in prazos if prazo.eh_autor]
    recente = max(autores, key=lambda prazo: prazo.evento) if autores else None
    escolhidos = list(abertos)
    if recente and all(item.evento != recente.evento for item in escolhidos):
        escolhidos.append(recente)
    escolhidos.sort(key=lambda prazo: (not prazo.eh_autor, -prazo.evento))
    return escolhidos


def _escolher_despacho(eventos: list[Evento], prazos: list[Prazo]) -> Evento | None:
    por_numero = {evento.numero: evento for evento in eventos}
    relevantes = _prazos_relevantes(prazos)
    candidatos = [prazo for prazo in relevantes if prazo.eh_autor and prazo.referido]
    if not candidatos:
        candidatos = [prazo for prazo in relevantes if prazo.referido]
    for prazo in sorted(candidatos, key=lambda item: item.evento, reverse=True):
        evento = por_numero.get(prazo.referido or 0)
        if evento and evento.eh_decisao and evento.documentos:
            return evento
    decisoes = [evento for evento in eventos if evento.eh_decisao and evento.documentos]
    if not decisoes:
        return None
    return max(decisoes, key=lambda evento: evento.numero)


_ROTULO_PARTE = {
    "AUTOR": "Autor",
    "REU": "Réu",
    "PERITO": "Perito",
    "EXEQUENTE": "Exequente",
    "EXECUTADO": "Executado",
}


def _linha_prazo(prazo: Prazo) -> str:
    papel = _ROTULO_PARTE.get(prazo.parte, prazo.parte.title() if prazo.parte else "Parte")
    quem = f"{papel} — {prazo.parte_nome}" if prazo.parte_nome else papel
    periodo = ""
    if prazo.inicio or prazo.final:
        periodo = f" — {prazo.inicio or '?'} a {prazo.final or '?'}"
    if prazo.dias == "1":
        dias = "1 dia — "
    elif prazo.dias:
        dias = f"{prazo.dias} dias — "
    else:
        dias = ""
    ref = f", decisão {prazo.referido}" if prazo.referido else ""
    return f"• {quem} — {dias}{prazo.status}{periodo} (evento {prazo.evento}{ref})"


def _eventos(documento) -> list[Evento]:
    eventos: list[Evento] = []
    for linha in documento.xpath("//tr[td[contains(@class,'infraEventoDescricao')]]"):
        colunas = linha.xpath("./td")
        if len(colunas) < 5:
            continue
        numero = _inteiro(_texto(colunas[0]))
        if numero is None:
            continue
        rotulo = _texto_nos(
            colunas[2].xpath(".//label[contains(@class,'infraEventoDescricao')]")
        ) or _texto(colunas[2])
        docs: list[Documento] = []
        for link in colunas[4].xpath(".//a[@href]"):
            href = link.get("href") or ""
            if href_documento(href):
                docs.append(Documento(_texto(link) or "documento", href))
        eventos.append(
            Evento(
                numero=numero,
                data=_texto(colunas[1]),
                rotulo=rotulo,
                descricao=_texto(colunas[2]),
                documentos=docs,
            )
        )
    return eventos


def _prazos(documento) -> list[Prazo]:
    prazos: list[Prazo] = []
    for linha in documento.xpath("//tr[td[contains(@class,'infraEventoDescricao')]]"):
        colunas = linha.xpath("./td")
        if len(colunas) < 3:
            continue
        numero = _inteiro(_texto(colunas[0]))
        descricao = _texto(colunas[2])
        if numero is None or "Prazo:" not in descricao and "Status:" not in descricao:
            continue
        parte_el = colunas[2].xpath(".//span[contains(@class,'infraEventoPrazoParte')]")
        parte = (parte_el[0].get("data-parte") or "").strip().upper() if parte_el else ""
        parte_nome = ""
        match_nome = re.search(
            r"\((?:AUTOR|R[ÉE]U|PERITO|EXEQUENTE|EXECUTADO)\s*[-–]\s*([^)]+)\)",
            descricao,
            flags=re.I,
        )
        if match_nome:
            parte_nome = re.sub(r"\s+", " ", match_nome.group(1)).strip()
        dias = _grupo(r"Prazo:\s*(\d+)\s*dia", descricao)
        status = _grupo(
            r"Status:\s*(.+?)(?:\s+Data inicial|\s+Data final|$)",
            descricao,
        )
        if not status:
            continue
        prazos.append(
            Prazo(
                evento=numero,
                parte=parte,
                parte_nome=parte_nome,
                dias=dias,
                status=status.strip(),
                inicio=_data(
                    r"Data inicial da contagem do prazo:\s*(\d{2}/\d{2}/\d{4})",
                    descricao,
                ),
                final=_data(r"Data final:\s*(\d{2}/\d{2}/\d{4})", descricao),
                referido=_inteiro(
                    _grupo(r"Refer\.\s*ao Evento:?\s*(\d+)", descricao)
                ),
            )
        )
    return prazos


def _partes_da_pagina(documento) -> tuple[list[str], list[str]]:
    reus: list[str] = []
    peritos: list[str] = []
    for no in documento.xpath("//*[@data-parte and contains(@class, 'infraNomeParte')]"):
        parte = _sem_acento(no.get("data-parte") or "").upper()
        nome = _texto(no)
        if not nome:
            continue
        if parte == "PERITO":
            _incluir_nome(peritos, nome)
        elif parte in _PARTES_REU:
            _incluir_nome(reus, nome)
    return reus, peritos


def _incluir_nome(nomes: list[str], nome: str) -> None:
    if nome.casefold() not in {item.casefold() for item in nomes}:
        nomes.append(nome)


def _autor_da_pagina(documento) -> str:
    for cabecalho in documento.xpath("//th"):
        if _sem_acento(_texto(cabecalho)).upper() != "AUTORES":
            continue
        tabelas = cabecalho.xpath("ancestor::table[1]")
        if not tabelas:
            continue
        for celula in tabelas[0].xpath(".//tr/td[1]"):
            nome = _texto(celula)
            if " " not in nome or _CNJ.search(nome):
                continue
            return nome
    return ""


def _texto(no) -> str:
    bruto = no.text_content() if hasattr(no, "text_content") else str(no)
    return re.sub(r"\s+", " ", bruto.replace("\xa0", " ")).strip()


def _texto_nos(nos) -> str:
    return " ".join(_texto(no) for no in nos if _texto(no)).strip()


def _inteiro(valor: str | None) -> int | None:
    if not valor:
        return None
    match = re.search(r"\d+", valor)
    return int(match.group(0)) if match else None


def _grupo(padrao: str, texto: str) -> str:
    match = re.search(padrao, texto, flags=re.I)
    return match.group(1).strip() if match else ""


def _data(padrao: str, texto: str) -> str:
    return _grupo(padrao, texto)


def _sem_acento(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto or "")
    return "".join(ch for ch in normalizado if not unicodedata.combining(ch)).translate(
        _SEM_ACENTO
    )


def caminho_destino(pasta: Path, nome: str) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta / nome
