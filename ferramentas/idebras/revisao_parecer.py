"""Finaliza revisões de parecer no Idebras com os PDFs da pasta de rede."""

from __future__ import annotations

import html as html_lib
import logging
import re
import shutil
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ferramentas.idebras.aspnet import (
    AspNetSession,
    login,
    parse_form_fields,
    parse_hidden_fields,
)
from ferramentas.idebras.config import REVISAO_PARECER_DIR

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]

PATH = "/AnaliseParecer/RevisaoParecer"
PASTAS_IGNORADAS = {"problemas", "logs"}

CPF_RE = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b")
CPF_LABEL_RE = re.compile(r"CPF:\s*([\d.\-]+)", re.I)
NOME_LINHA_RE = re.compile(r"^\s*([^(]+?)\s*\((\d+)\)")
ROW_BTN_RE = re.compile(
    r"__doPostBack\('ctl00\$body\$gridrevisaoparecer\$(ctl\d+)\$ctl(?:00|01|02)'",
    re.I,
)
TEMP_ARQUIVO_RE = re.compile(
    r"/Temp/([^\"'<>\s]+\.(?:docx|doc|pdf))",
    re.I,
)
TOASTR_ERRO_RE = re.compile(
    r"toastr\.(?:error|warning)\(\s*['\"]([^'\"]+)['\"]",
    re.I,
)
SWEET_ERRO_RE = re.compile(
    r"sweetAlert\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]error['\"]",
    re.I,
)


@dataclass
class ItemRevisao:
    nome: str
    cpf: str
    arquivo_esperado: str
    observacao: str
    row_ctl: str

    @property
    def rotulo(self) -> str:
        cpf_fmt = _formatar_cpf(self.cpf) or self.cpf
        return f"{self.nome} ({cpf_fmt})"


@dataclass
class ArquivoLocal:
    path: Path
    stem: str
    cpf: str
    nome_compacto: str
    em_finalizados: bool


@dataclass
class ParRevisao:
    item: ItemRevisao
    pdf: ArquivoLocal


@dataclass
class PlanoRevisao:
    session: AspNetSession
    html: str
    pasta: Path
    pares: list[ParRevisao] = field(default_factory=list)
    faltando: list[ItemRevisao] = field(default_factory=list)
    duplicados: list[str] = field(default_factory=list)
    so_finalizados: list[str] = field(default_factory=list)
    sobrando: list[str] = field(default_factory=list)
    words_baixados: list[str] = field(default_factory=list)
    falhas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


@dataclass
class ResultadoRevisao:
    a_finalizar: list[str] = field(default_factory=list)
    enviados: list[str] = field(default_factory=list)
    faltando_pdf: list[str] = field(default_factory=list)
    words_baixados: list[str] = field(default_factory=list)
    duplicados: list[str] = field(default_factory=list)
    so_finalizados: list[str] = field(default_factory=list)
    sobrando_pasta: list[str] = field(default_factory=list)
    falhas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    log_path: Path | None = None
    simulacao: bool = False
    cancelado: bool = False
    operacao: str = "preview"

    def mensagem_slack(self) -> str:
        return self.texto_log(markdown=True)

    def tem_word_novo(self) -> bool:
        return any(
            "já estava" not in w.lower() and "já existia" not in w.lower()
            for w in self.words_baixados
        )

    def texto_log(self, *, markdown: bool = False) -> str:
        def titulo(texto: str) -> str:
            return f"*{texto}*" if markdown else texto

        def item(texto: str) -> str:
            return f"• {texto}" if markdown else f"  - {texto}"

        if self.cancelado:
            modo = "cancelado pelo usuário"
        elif self.operacao == "download":
            modo = "download"
        elif self.simulacao:
            modo = "simulação"
        else:
            modo = "envio"

        cabeca = (
            f"*Revisão do parecer* (_{modo}_)"
            if markdown
            else f"Revisão do parecer — {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} ({modo})"
        )
        linhas = [cabeca]

        if self.operacao == "download":
            linhas += [
                "",
                titulo(
                    f"PDFs já disponíveis para finalizar ({len(self.a_finalizar)}):"
                ),
            ]
            linhas.extend(item(x) for x in (self.a_finalizar or ["(nenhum)"]))
        elif self.simulacao or self.cancelado:
            linhas += [
                "",
                titulo(f"Pareceres a serem finalizados ({len(self.a_finalizar)}):"),
            ]
            linhas.extend(item(x) for x in (self.a_finalizar or ["(nenhum)"]))
        else:
            linhas += [
                "",
                titulo(f"Finalizados no Idebras ({len(self.enviados)}):"),
            ]
            linhas.extend(item(x) for x in (self.enviados or ["(nenhum)"]))

        linhas += [
            "",
            titulo(
                f"Duplicados — arquivo na subpasta e também em FINALIZADOS "
                f"({len(self.duplicados)}):"
            ),
        ]
        linhas.extend(item(x) for x in (self.duplicados or ["(nenhum)"]))
        linhas += [
            "",
            titulo(
                f"Faltando PDF — não encontrado em lugar nenhum "
                f"({len(self.faltando_pdf)}):"
            ),
        ]
        linhas.extend(item(x) for x in (self.faltando_pdf or ["(nenhuma)"]))
        if self.words_baixados:
            linhas += [
                "",
                titulo(
                    f"Word automático baixado para a pasta Bot "
                    f"({len(self.words_baixados)}):"
                ),
            ]
            linhas.extend(item(x) for x in self.words_baixados)
        linhas += [
            "",
            titulo(
                f"PDF só em FINALIZADOS, mas ainda na lista do Idebras "
                f"({len(self.so_finalizados)}):"
            ),
        ]
        linhas.extend(item(x) for x in (self.so_finalizados or ["(nenhum)"]))
        linhas += [
            "",
            titulo(
                f"Sobrando na pasta — PDF sem revisão correspondente "
                f"({len(self.sobrando_pasta)}):"
            ),
        ]
        linhas.extend(item(x) for x in (self.sobrando_pasta or ["(nenhum)"]))
        if self.avisos:
            linhas += ["", titulo(f"Avisos ({len(self.avisos)}):")]
            linhas.extend(item(x) for x in self.avisos)
        linhas += ["", titulo(f"Falhas ({len(self.falhas)}):")]
        linhas.extend(item(x) for x in (self.falhas or ["(nenhuma)"]))
        if self.log_path:
            linhas.append(
                f"\nLog: `{self.log_path}`" if markdown else f"\nLog: {self.log_path}"
            )
        if (
            self.simulacao
            and self.operacao != "download"
            and self.a_finalizar
            and markdown
        ):
            linhas += [
                "",
                "────────────────",
                "",
                "*Responda `sim` ou `confirmar` neste canal para finalizar os pareceres listados.*",
                "*Responda `não` ou `cancelar` para descartar esta prévia.*",
            ]
        linhas.append("")
        return "\n".join(linhas)


def _somente_digitos(valor: str) -> str:
    return re.sub(r"\D+", "", valor or "")


def _formatar_cpf(cpf: str) -> str:
    d = _somente_digitos(cpf)
    if len(d) != 11:
        return cpf
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def compactar_nome(nome: str) -> str:
    nfd = unicodedata.normalize("NFKD", nome or "")
    sem_acento = "".join(c for c in nfd if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z0-9]", "", sem_acento).upper()


def parse_stem_arquivo(stem: str) -> tuple[str, str]:
    """Extrai (cpf, nome_compacto) do stem do arquivo."""
    parts = [p for p in stem.split(".")]
    cpf = ""
    if parts and parts[-1].isdigit() and len(parts[-1]) == 11:
        cpf = parts[-1]
        corpo = parts[:-1]
    else:
        corpo = parts
    nome = ""
    for part in reversed(corpo):
        if part and not part.isdigit():
            nome = compactar_nome(part)
            break
    return cpf, nome


def pasta_bot(raiz: Path) -> Path:
    dest = raiz / "Bot"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def pasta_logs(raiz: Path) -> Path:
    dest = pasta_bot(raiz) / "logs"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def _em_finalizados(path: Path) -> bool:
    return any(part.lower() == "finalizados" for part in path.parts)


def _ignorar(path: Path) -> bool:
    return any(part.lower() in PASTAS_IGNORADAS for part in path.parts)


def listar_arquivos_pasta(pasta: Path, *exts: str) -> list[ArquivoLocal]:
    if not pasta.exists():
        raise ValueError(f"Pasta de revisão não encontrada: {pasta}")

    encontrados: list[ArquivoLocal] = []
    vistos: set[Path] = set()
    for ext in exts:
        for path in pasta.rglob(f"*{ext}"):
            if not path.is_file() or _ignorar(path):
                continue
            resolved = path.resolve()
            if resolved in vistos:
                continue
            vistos.add(resolved)
            cpf, nome = parse_stem_arquivo(path.stem)
            encontrados.append(
                ArquivoLocal(
                    path=path,
                    stem=path.stem,
                    cpf=cpf,
                    nome_compacto=nome,
                    em_finalizados=_em_finalizados(path),
                )
            )
    encontrados.sort(key=lambda a: str(a.path).lower())
    return encontrados


def _texto_celula(html: str) -> str:
    texto = re.sub(r"<\s*br\s*/?\s*>", "\n", html, flags=re.I)
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = html_lib.unescape(texto)
    linhas = [" ".join(linha.split()) for linha in texto.splitlines()]
    return "\n".join(linha for linha in linhas if linha)


def parse_itens_revisao(html: str) -> list[ItemRevisao]:
    decoded = html_lib.unescape(html)
    itens: list[ItemRevisao] = []
    for row in re.finditer(
        r'<tr class="table-idebras-rows">(.*?)</tr>',
        decoded,
        re.S,
    ):
        row_m = ROW_BTN_RE.search(row.group(1))
        if not row_m:
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S)
        if len(tds) < 2:
            continue
        col_mutuario = _texto_celula(tds[0])
        observacao = _texto_celula(tds[1])
        linhas = [ln.strip() for ln in col_mutuario.splitlines() if ln.strip()]
        if not linhas:
            continue

        nome = linhas[0]
        m_nome = NOME_LINHA_RE.match(linhas[0])
        if m_nome:
            nome = m_nome.group(1).strip()

        cpf = ""
        m_cpf = CPF_LABEL_RE.search(col_mutuario)
        if m_cpf:
            cpf = _somente_digitos(m_cpf.group(1))
        if not cpf:
            m_cpf = CPF_RE.search(col_mutuario)
            if m_cpf:
                cpf = _somente_digitos(m_cpf.group(1))

        arquivo_esperado = ""
        for linha in reversed(linhas):
            if "..." in linha or re.search(r"\d{3,}", linha):
                if "CPF" in linha.upper() or linha.lower().startswith("endere"):
                    continue
                arquivo_esperado = linha.replace("...", "").strip()
                break

        itens.append(
            ItemRevisao(
                nome=nome,
                cpf=cpf,
                arquivo_esperado=arquivo_esperado,
                observacao=observacao,
                row_ctl=row_m.group(1),
            )
        )
    return itens


def _indice_por_chave(arquivos: list[ArquivoLocal]) -> tuple[
    dict[str, list[ArquivoLocal]],
    dict[str, list[ArquivoLocal]],
    dict[str, list[ArquivoLocal]],
]:
    por_cpf: dict[str, list[ArquivoLocal]] = {}
    por_nome: dict[str, list[ArquivoLocal]] = {}
    por_stem: dict[str, list[ArquivoLocal]] = {}
    for arq in arquivos:
        if arq.cpf:
            por_cpf.setdefault(arq.cpf, []).append(arq)
        if arq.nome_compacto:
            por_nome.setdefault(arq.nome_compacto, []).append(arq)
        por_stem.setdefault(arq.stem.lower(), []).append(arq)
    return por_cpf, por_nome, por_stem


def _candidatos_arquivo(
    item: ItemRevisao,
    por_cpf: dict[str, list[ArquivoLocal]],
    por_nome: dict[str, list[ArquivoLocal]],
) -> list[ArquivoLocal]:
    if item.cpf and item.cpf in por_cpf:
        return list(por_cpf[item.cpf])
    chave = compactar_nome(item.nome)
    if chave and chave in por_nome:
        return list(por_nome[chave])
    return []


def _casar(
    itens: list[ItemRevisao],
    pdfs: list[ArquivoLocal],
    outros_finalizados: list[ArquivoLocal],
) -> tuple[
    list[ParRevisao],
    list[ItemRevisao],
    list[str],
    list[str],
    list[ArquivoLocal],
    list[str],
]:
    pendentes = [p for p in pdfs if not p.em_finalizados]
    finalizados = [p for p in pdfs if p.em_finalizados] + [
        a for a in outros_finalizados if a.em_finalizados
    ]

    por_cpf_p, por_nome_p, _por_stem_p = _indice_por_chave(pendentes)
    por_cpf_f, _por_nome_f, por_stem_f = _indice_por_chave(finalizados)

    pares: list[ParRevisao] = []
    duplicados: list[str] = []
    so_finalizados: list[str] = []
    falhas: list[str] = []
    usados_pendentes: set[int] = set()
    usados_itens: set[int] = set()

    for item in itens:
        cands_p = _candidatos_arquivo(item, por_cpf_p, por_nome_p)
        cands_f = _candidatos_arquivo(item, por_cpf_f, _por_nome_f)

        if len(cands_p) > 1:
            nomes = ", ".join(str(c.path) for c in cands_p)
            falhas.append(f"{item.rotulo}: PDFs pendentes ambíguos ({nomes})")
            usados_itens.add(id(item))
            for c in cands_p:
                usados_pendentes.add(id(c))
            continue

        if cands_p and cands_f:
            pend = cands_p[0]
            fin = cands_f[0]
            duplicados.append(
                f"{item.rotulo}: {pend.path.name} está em "
                f"{pend.path.parent} e também em {fin.path.parent}"
            )
            usados_itens.add(id(item))
            usados_pendentes.add(id(pend))
            continue

        if cands_p:
            pdf = cands_p[0]
            stem_dup = por_stem_f.get(pdf.stem.lower(), [])
            if stem_dup:
                duplicados.append(
                    f"{item.rotulo}: {pdf.path.name} está em "
                    f"{pdf.path.parent} e também em {stem_dup[0].path.parent}"
                )
                usados_itens.add(id(item))
                usados_pendentes.add(id(pdf))
                continue
            pares.append(ParRevisao(item=item, pdf=pdf))
            usados_itens.add(id(item))
            usados_pendentes.add(id(pdf))
            continue

        if cands_f:
            so_finalizados.append(
                f"{item.rotulo}: {cands_f[0].path.name} só em {cands_f[0].path.parent}"
            )
            usados_itens.add(id(item))
            continue

    faltando = [item for item in itens if id(item) not in usados_itens]
    sobrando = [p for p in pendentes if id(p) not in usados_pendentes]
    return pares, faltando, duplicados, so_finalizados, sobrando, falhas


def _payload(html: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    fields = parse_form_fields(html)
    hidden = parse_hidden_fields(html)
    out = {**fields, **hidden}
    out.setdefault("__EVENTTARGET", "")
    out.setdefault("__EVENTARGUMENT", "")
    if extra:
        out.update(extra)
    for chave in (
        "ctl00$body$btnpesquisarfluxo",
        "ctl00$body$btninserirpdf",
        "ctl00$body$btnsalvarpdf",
        "ctl00$body$btntransferirfluxo",
        "ctl00$body$btntransferir",
        "ctl00$body$btnsalvarcadastro",
        "ctl00$body$btndownload",
        "ctl00$body$btngerar",
        "ctl00$body$btneditarcadastro",
        "ctl00$body$btnverdocumentos",
        "ctl00$body$btnfotosimovel",
        "ctl00$body$btnfotosparecer",
        "ctl00$body$btnverrevisao",
        "ctl00$btntrocarstatususuario",
    ):
        if extra and chave in extra:
            continue
        out.pop(chave, None)
    return out


def _abrir_lista(session: AspNetSession) -> str:
    html = session.get_html(PATH)
    if "gridrevisaoparecer" not in html.lower() and "droppagesize" not in html.lower():
        raise RuntimeError(
            f"Página inesperada em {PATH}. Login pode ter expirado ou a URL mudou."
        )
    fields = _payload(
        html,
        {
            "__EVENTTARGET": "ctl00$body$droppagesize",
            "__EVENTARGUMENT": "",
            "ctl00$body$droppagesize": "0",
        },
    )
    html = session.post_html(PATH, fields)
    if "gridrevisaoparecer" not in html.lower():
        raise RuntimeError("Não foi possível carregar a grade de revisão (Todos).")
    return html


def _erros_pagina(html: str) -> str | None:
    mensagens = [m.group(1).strip() for m in TOASTR_ERRO_RE.finditer(html)]
    mensagens += [
        f"{m.group(1)}: {m.group(2)}".strip() for m in SWEET_ERRO_RE.finditer(html)
    ]
    if mensagens:
        return " | ".join(mensagens)
    return None


def _item_ainda_na_lista(html: str, cpf: str) -> bool:
    if not cpf:
        return False
    return any(item.cpf == cpf for item in parse_itens_revisao(html))


def _word_existente_bot(bot_dir: Path, item: ItemRevisao) -> Path | None:
    if not bot_dir.exists():
        return None
    for path in bot_dir.glob("*.docx"):
        cpf, nome = parse_stem_arquivo(path.stem)
        if item.cpf and cpf == item.cpf:
            return path
        if nome and nome == compactar_nome(item.nome):
            return path
    return None


def _baixar_word_automatico(
    session: AspNetSession,
    html: str,
    item: ItemRevisao,
    dest_dir: Path,
) -> tuple[str, Path, str]:
    """Clica em Download do parecer gerado automático e salva o Word.

    Retorna (html_atualizado, destino, descricao).
    """
    existente = _word_existente_bot(dest_dir, item)
    if existente:
        return html, existente, f"já estava em Bot/{existente.name}"

    target = f"ctl00$body$gridrevisaoparecer${item.row_ctl}$ctl00"
    _, data, ctype = session.post(
        PATH,
        _payload(html, {"__EVENTTARGET": target, "__EVENTARGUMENT": ""}),
        timeout=180,
    )
    corpo = data.decode("utf-8", errors="replace")
    if "html" in (ctype or "").lower() or data[:15].lstrip().startswith(b"<!DOCTYPE"):
        html = corpo
    match = TEMP_ARQUIVO_RE.search(corpo)
    if not match:
        raise RuntimeError(
            "O Idebras não gerou o arquivo em /Temp/ após "
            '"Download do parecer gerado automático".'
        )
    rel = f"/Temp/{match.group(1)}"
    _, arquivo, arq_ctype = session.get(rel)
    nome = Path(match.group(1)).name
    if arquivo[:2] != b"PK" and not nome.lower().endswith(".pdf"):
        if "html" in (arq_ctype or "").lower():
            raise RuntimeError(f"Download de {rel} não parece Word/PDF.")
    dest = dest_dir / nome
    if dest.exists():
        return html, dest, f"já existia em Bot/{dest.name}"
    dest.write_bytes(arquivo)
    logger.info("Word automático salvo em %s", dest)
    return html, dest, f"salvo em Bot/{dest.name}"


def _mover_finalizados(pdf: Path) -> list[str]:
    """Move PDF e Word irmão para FINALIZADOS. Não sobrescreve duplicados."""
    avisos: list[str] = []
    destino_dir = pdf.parent / "FINALIZADOS"
    destino_dir.mkdir(parents=True, exist_ok=True)
    origem_unicas: list[Path] = []
    for origem in (pdf, pdf.with_suffix(".docx")):
        if origem.exists() and origem.is_file() and origem not in origem_unicas:
            origem_unicas.append(origem)
    if pdf.exists() and pdf.with_suffix(".docx") not in origem_unicas:
        avisos.append(
            f"{pdf.name}: Word correspondente não encontrado ao lado do PDF."
        )
    for origem in origem_unicas:
        destino = destino_dir / origem.name
        if destino.exists():
            avisos.append(
                f"Duplicado ao mover: {origem.name} já existe em {destino_dir}. "
                f"O arquivo foi deixado em {origem.parent}."
            )
            continue
        shutil.move(str(origem), str(destino))
        logger.info("Movido para FINALIZADOS: %s", destino)
    return avisos


ARQUIVO_SITUACAO_DOWNLOAD = "ultima_situacao_download.txt"


def assinatura_situacao(resultado: ResultadoRevisao) -> str:
    """Resumo estável da situação, sem data/hora, para comparar execuções."""
    campos = [
        ("operacao", [resultado.operacao]),
        ("a_finalizar", resultado.a_finalizar),
        ("enviados", resultado.enviados),
        ("faltando_pdf", resultado.faltando_pdf),
        ("words_baixados", resultado.words_baixados),
        ("duplicados", resultado.duplicados),
        ("so_finalizados", resultado.so_finalizados),
        ("sobrando_pasta", resultado.sobrando_pasta),
        ("falhas", resultado.falhas),
        ("avisos", resultado.avisos),
    ]
    linhas: list[str] = []
    for nome, valores in campos:
        linhas.append(f"[{nome}]")
        linhas.extend(sorted(valores))
    return "\n".join(linhas) + "\n"


def _caminho_situacao_download(pasta: Path) -> Path:
    return pasta_logs(pasta) / ARQUIVO_SITUACAO_DOWNLOAD


def situacao_igual_ao_ultimo_download(pasta: Path, resultado: ResultadoRevisao) -> bool:
    path = _caminho_situacao_download(pasta)
    if not path.exists():
        return False
    atual = assinatura_situacao(resultado)
    anterior = path.read_text(encoding="utf-8")
    return anterior == atual


def registrar_situacao_download(pasta: Path, resultado: ResultadoRevisao) -> None:
    path = _caminho_situacao_download(pasta)
    path.write_text(assinatura_situacao(resultado), encoding="utf-8")


def gravar_log_download_horario(pasta: Path, resultado: ResultadoRevisao) -> bool:
    """Grava log do download horário só se a situação mudou. Retorna True se gravou."""
    if situacao_igual_ao_ultimo_download(pasta, resultado):
        logger.info(
            "Download horário da revisão: situação igual à da última hora; log omitido."
        )
        return False
    _gravar_log(pasta, resultado)
    registrar_situacao_download(pasta, resultado)
    return True


def _gravar_log(pasta: Path, resultado: ResultadoRevisao) -> Path:
    destino_dir = pasta_logs(pasta)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    if resultado.cancelado:
        prefixo = "cancelado"
    elif resultado.operacao == "download":
        prefixo = "download"
    elif resultado.simulacao:
        prefixo = "simular"
    else:
        prefixo = "envio"
    path = destino_dir / f"log_revisao_{prefixo}_{stamp}.txt"
    extra = 2
    while path.exists():
        path = destino_dir / f"log_revisao_{prefixo}_{stamp}_{extra}.txt"
        extra += 1
    path.write_text(resultado.texto_log(), encoding="utf-8")
    resultado.log_path = path
    logger.info("Log gravado em %s", path)
    return path


def resultado_do_plano(
    plano: PlanoRevisao,
    *,
    simulacao: bool = True,
    cancelado: bool = False,
    operacao: str | None = None,
) -> ResultadoRevisao:
    if operacao is None:
        if simulacao:
            operacao = "preview"
        else:
            operacao = "envio"
    return ResultadoRevisao(
        a_finalizar=[
            f"{par.item.rotulo} <- {par.pdf.path.name} ({par.pdf.path.parent.name})"
            for par in plano.pares
        ],
        faltando_pdf=[item.rotulo for item in plano.faltando],
        words_baixados=list(plano.words_baixados),
        duplicados=list(plano.duplicados),
        so_finalizados=list(plano.so_finalizados),
        sobrando_pasta=list(plano.sobrando),
        falhas=list(plano.falhas),
        avisos=list(plano.avisos),
        simulacao=simulacao,
        cancelado=cancelado,
        operacao=operacao,
    )


def montar_plano_revisao(
    *,
    pasta: Path | None = None,
    session: AspNetSession | None = None,
    apenas_cpf: str | None = None,
    baixar_word_faltante: bool = True,
    on_progress: ProgressCallback | None = None,
) -> PlanoRevisao:
    """Login, lista Todos, casa PDFs e baixa Word automático dos que faltam."""
    pasta = Path(pasta) if pasta is not None else REVISAO_PARECER_DIR
    if on_progress:
        on_progress("Lendo PDFs e Words da pasta de revisão…")
    arquivos = listar_arquivos_pasta(pasta, ".pdf", ".docx")
    pdfs = [a for a in arquivos if a.path.suffix.lower() == ".pdf"]
    words_fin = [
        a
        for a in arquivos
        if a.path.suffix.lower() == ".docx" and a.em_finalizados
    ]
    logger.info(
        "Arquivos na pasta: %s PDF(s), %s em FINALIZADOS.",
        len(pdfs),
        sum(1 for p in pdfs if p.em_finalizados),
    )

    if on_progress:
        on_progress("Fazendo login no Idebras…")
    session = login(session)

    if on_progress:
        on_progress("Carregando revisões (Todos)…")
    html = _abrir_lista(session)
    itens = parse_itens_revisao(html)
    logger.info("Revisões na grade: %s", len(itens))

    pares, faltando, duplicados, so_finalizados, sobrando, falhas = _casar(
        itens, pdfs, words_fin
    )
    if apenas_cpf:
        cpf_filtro = _somente_digitos(apenas_cpf)
        pares = [par for par in pares if par.item.cpf == cpf_filtro]
        faltando = [item for item in faltando if item.cpf == cpf_filtro]
        if not pares and not faltando:
            falhas.append(f"Nenhuma revisão encontrada para o CPF {apenas_cpf}.")

    plano = PlanoRevisao(
        session=session,
        html=html,
        pasta=pasta,
        pares=pares,
        faltando=faltando,
        duplicados=duplicados,
        so_finalizados=so_finalizados,
        sobrando=[
            f"{pdf.path.name} ({pdf.path.parent.name})" for pdf in sobrando
        ],
        falhas=falhas,
    )

    if baixar_word_faltante and faltando:
        bot_dir = pasta_bot(pasta)
        for i, item in enumerate(faltando, start=1):
            if on_progress:
                on_progress(
                    f"Baixando Word automático {i}/{len(faltando)}: {item.nome}…"
                )
            try:
                html, dest, desc = _baixar_word_automatico(
                    session, html, item, bot_dir
                )
                plano.html = html
                plano.words_baixados.append(f"{item.rotulo}: {desc}")
            except Exception as exc:
                logger.exception("Falha ao baixar Word automático de %s", item.rotulo)
                plano.falhas.append(
                    f"{item.rotulo}: falha no download automático ({exc})"
                )
                try:
                    html = _abrir_lista(session)
                    plano.html = html
                except Exception:
                    logger.exception("Não foi possível recarregar a lista após download")

    return plano


def _enviar_pdf(
    session: AspNetSession,
    lista_html: str,
    par: ParRevisao,
) -> str:
    """Visualizar → Inserir PDF → Salvar PDF. Devolve o HTML da lista após o envio."""
    item, pdf = par.item, par.pdf
    target = f"ctl00$body$gridrevisaoparecer${item.row_ctl}$ctl02"
    html = session.post_html(
        PATH,
        _payload(
            lista_html,
            {"__EVENTTARGET": target, "__EVENTARGUMENT": ""},
        ),
    )
    if "btninserirpdf" not in html.lower() and "fudocumento" not in html.lower():
        raise RuntimeError(
            f'Após "Visualizar dados do imóvel" não apareceu "Inserir PDF" '
            f"para {item.rotulo}."
        )

    html_detalhe = html
    if "btninserirpdf" in html.lower():
        html_apos = session.post_html(
            PATH,
            _payload(html, {"ctl00$body$btninserirpdf": "Inserir PDF"}),
        )
        if "fudocumento" in html_apos.lower() and "btnsalvarpdf" in html_apos.lower():
            html = html_apos
        else:
            html = html_detalhe

    if "fudocumento" not in html.lower() or "btnsalvarpdf" not in html.lower():
        raise RuntimeError(
            f"Não foi possível abrir o upload de PDF para {item.rotulo}."
        )

    conteudo = pdf.path.read_bytes()
    if not conteudo.startswith(b"%PDF"):
        raise RuntimeError(f"{pdf.path.name} não parece um PDF válido.")

    html = session.post_multipart_html(
        PATH,
        _payload(html, {"ctl00$body$btnsalvarpdf": "Salvar PDF"}),
        {
            "ctl00$body$fudocumento": (
                pdf.path.name,
                conteudo,
                "application/pdf",
            )
        },
        timeout=180,
    )

    erro = _erros_pagina(html)
    if erro:
        raise RuntimeError(erro)

    html = _abrir_lista(session)
    if _item_ainda_na_lista(html, item.cpf):
        extra = _erros_pagina(html)
        detalhe = f" {extra}" if extra else ""
        raise RuntimeError(
            "O parecer continuou na lista após Salvar PDF. "
            "Confira se o nome do arquivo é igual ao do parecer."
            + detalhe
        )
    return html


def executar_plano_revisao(
    plano: PlanoRevisao,
    *,
    on_progress: ProgressCallback | None = None,
) -> ResultadoRevisao:
    """Envia os pares já casados e move PDF+Word para FINALIZADOS."""
    resultado = resultado_do_plano(plano, simulacao=False)
    resultado.enviados = []
    html = plano.html
    session = plano.session

    for i, par in enumerate(plano.pares, start=1):
        rotulo = par.item.rotulo
        if on_progress:
            on_progress(f"Enviando {i}/{len(plano.pares)}: {par.item.nome}…")
        logger.info("Enviando PDF de %s (%s)", rotulo, par.pdf.path.name)
        try:
            itens_atual = parse_itens_revisao(html)
            atual = next(
                (item for item in itens_atual if item.cpf == par.item.cpf),
                None,
            )
            if atual is None:
                html = _abrir_lista(session)
                itens_atual = parse_itens_revisao(html)
                atual = next(
                    (item for item in itens_atual if item.cpf == par.item.cpf),
                    None,
                )
            if atual is None:
                resultado.falhas.append(f"{rotulo}: sumiu da lista antes do envio")
                continue
            par.item.row_ctl = atual.row_ctl
            html = _enviar_pdf(session, html, par)
            avisos_move = _mover_finalizados(par.pdf.path)
            resultado.enviados.append(f"{rotulo} <- {par.pdf.path.name}")
            resultado.avisos.extend(
                f"{rotulo}: {aviso}" for aviso in avisos_move
            )
        except Exception as exc:
            logger.exception("Falha ao finalizar %s", rotulo)
            resultado.falhas.append(f"{rotulo}: {exc}")
            try:
                html = _abrir_lista(session)
            except Exception:
                logger.exception("Não foi possível recarregar a lista após falha")

    plano.html = html
    _gravar_log(plano.pasta, resultado)
    return resultado


def finalizar_revisoes_parecer(
    *,
    pasta: Path | None = None,
    session: AspNetSession | None = None,
    simular: bool = False,
    baixar_word_faltante: bool | None = None,
    apenas_cpf: str | None = None,
    on_progress: ProgressCallback | None = None,
    modo: str | None = None,
    gravar_log: bool = True,
) -> ResultadoRevisao:
    """Casa PDFs da pasta com a grade de Revisão.

    modo:
      - preview: baixa Words faltantes e lista o que seria finalizado
      - download: só baixa Words para a pasta Bot
      - finalizar: envia os PDFs (sem baixar Word)
    """
    if modo is None:
        modo = "preview" if simular else "finalizar"
    if modo not in {"preview", "download", "finalizar"}:
        raise ValueError(f"Modo de revisão inválido: {modo}")
    if baixar_word_faltante is None:
        baixar_word_faltante = modo in {"preview", "download"}
    plano = montar_plano_revisao(
        pasta=pasta,
        session=session,
        apenas_cpf=apenas_cpf,
        baixar_word_faltante=baixar_word_faltante,
        on_progress=on_progress,
    )
    if modo != "finalizar":
        resultado = resultado_do_plano(
            plano,
            simulacao=True,
            operacao="download" if modo == "download" else "preview",
        )
        if gravar_log:
            _gravar_log(plano.pasta, resultado)
        return resultado
    return executar_plano_revisao(plano, on_progress=on_progress)
