"""Consulta o eproc por HTTP com os cookies de uma sessão já aberta. Sem navegador."""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
import shutil
import ssl
import subprocess
import tempfile
import time
import zipfile
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    HTTPSHandler,
    Request,
    build_opener,
)

import truststore
from lxml import html as lxml_html

from ferramentas.eproc.leitura import (
    ConsultaInterrompida,
    LeituraProcesso,
    juntar_partes,
    ler_processo,
    nome_arquivo_zip,
)
from ferramentas.eproc.seguranca import (
    _HOSTS_EPROC as _HOSTS,
    acao_da_url,
    href_documento,
    pedido_http_permitido,
)

logger = logging.getLogger(__name__)

_RAIZ = Path(__file__).resolve().parents[2]
_COOKIES = _RAIZ / "tmp" / "eproc-sessao" / "cookies.json"
_AGENTE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
_CAMPO_BUSCA = "txtNumProcessoPesquisaRapida"
_CAMPO_LOGIN = "txtUsuario"
_ESPERA_ZIP = 15 * 60


class SessaoExpirada(ConsultaInterrompida):
    """O eproc voltou para a tela de login: o cookie de sessão morreu."""


class _Redirecionar(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if "externo_controlador" in urlparse(newurl).path:
            raise SessaoExpirada("A sessão do eproc expirou.")
        if not pedido_http_permitido("GET", newurl):
            raise ConsultaInterrompida(
                f"O eproc mandou para a tela '{acao_da_url(newurl) or newurl}', que não está prevista. Parei."
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ClienteEproc:
    def __init__(self, base: str, cookies: list[dict]) -> None:
        self._base = base
        self._cookies = CookieJar()
        for dados in cookies:
            if dados.get("domain", "").lstrip(".") in _HOSTS:
                self._cookies.set_cookie(_cookie(dados))
        self._abridor = build_opener(
            HTTPSHandler(context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)),
            HTTPCookieProcessor(self._cookies),
            _Redirecionar(),
        )
        self._tela_busca: tuple[str, str] | None = None
        self._processo: tuple[str, str] | None = None

    @classmethod
    def carregar(cls, base: str) -> ClienteEproc | None:
        if not _COOKIES.is_file():
            return None
        try:
            cookies = json.loads(_COOKIES.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return cls(base, cookies)

    def salvar(self) -> None:
        _COOKIES.parent.mkdir(parents=True, exist_ok=True)
        cookies = [
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "expires": cookie.expires or -1,
                "secure": cookie.secure,
            }
            for cookie in self._cookies
        ]
        _COOKIES.write_text(json.dumps(cookies), encoding="utf-8")

    def logado(self) -> bool:
        try:
            url, texto = self._ler(self._base)
        except SessaoExpirada:
            return False
        if _CAMPO_BUSCA not in texto:
            return False
        self._tela_busca = (url, texto)
        return True

    def ler(self, numero: str) -> LeituraProcesso:
        url, pagina = self._abrir_processo(numero)
        leitura = ler_processo(pagina, numero)
        juntar_partes(leitura, self._partes_ocultas(url, pagina))
        self._processo = (url, pagina)
        return leitura

    def baixar_documento(self, href: str, destino: Path, base: str = "", salto: int = 0) -> Path:
        if not href_documento(href):
            raise ConsultaInterrompida(
                "O link do documento não é só de leitura. Nada foi baixado além do previsto."
            )
        url = urljoin(base or self._url_processo(), href)
        final, corpo, tipo = self._pedir(url)
        parece_html = corpo[:200].lstrip().lower().startswith((b"<", b"<!"))
        if corpo.startswith(b"%PDF") or ("pdf" in tipo and not parece_html):
            if len(corpo) < 100:
                raise ConsultaInterrompida("O arquivo do documento veio vazio.")
            destino.write_bytes(corpo)
            return destino
        texto = _decodificar(corpo, tipo)
        proximo = _proximo_documento(texto) if salto < 2 else ""
        if proximo and proximo != href:
            return self.baixar_documento(proximo, destino, final, salto + 1)
        if salto >= 1 and corpo.strip():
            # Os bytes originais: o HTML declara ISO-8859-1 e o Chrome lê o arquivo assim.
            pagina = destino.with_suffix(".html")
            pagina.write_bytes(corpo)
            if _html_para_pdf(pagina, destino):
                pagina.unlink(missing_ok=True)
                return destino
            return pagina
        raise ConsultaInterrompida(
            "O eproc não devolveu o PDF do documento. Parei para não abrir outra tela."
        )

    def baixar_completo(self, pasta: Path, nome: str, progresso) -> Path:
        url_processo, pagina = self._processo or ("", "")
        botao = re.search(
            r"""location\.href\s*=\s*['"](controlador\.php\?acao=selecionar_processos_agendar_arquivo_completo[^'"]+)['"]""",
            pagina,
        )
        if not botao:
            raise ConsultaInterrompida("Não achei o botão Download Completo nesta página.")
        url_agenda = urljoin(url_processo, html_lib.unescape(botao.group(1)))
        _, agenda = self._ler(url_agenda)
        if not _zip_pronto(agenda):
            if 'id="btnGerar"' in agenda:
                formulario = _formulario(agenda, "frmProcessosSelecionados")
                progresso("Pedindo ao tribunal o arquivo completo…")
                self._pedir(
                    urljoin(url_agenda, formulario.get("action") or ""),
                    _campos_formulario(formulario),
                )
            agenda = self._esperar_zip(url_agenda, progresso)
        return self._salvar_zip(url_agenda, agenda, pasta, nome, progresso)

    def _esperar_zip(self, url_agenda: str, progresso) -> str:
        inicio = time.monotonic()
        avisado = 0.0
        while time.monotonic() - inicio < _ESPERA_ZIP:
            if time.monotonic() - avisado >= 60:
                progresso("Aguardando o tribunal gerar o arquivo completo…")
                avisado = time.monotonic()
            time.sleep(15)
            _, agenda = self._ler(url_agenda)
            if _zip_pronto(agenda):
                return agenda
        raise ConsultaInterrompida("O tribunal levou mais de 15 minutos para gerar o arquivo completo.")

    def _salvar_zip(self, url_agenda: str, agenda: str, pasta: Path, nome: str, progresso) -> Path:
        alvo = re.search(r"""attr\(\s*["']action["']\s*,\s*["']([^"']+zip=S[^"']+)["']\s*\)""", agenda)
        if not alvo:
            raise ConsultaInterrompida("O arquivo completo ficou pronto, mas não achei o endereço do ZIP.")
        formulario = _formulario(agenda, "frmProcessosSelecionados")
        progresso("O tribunal está montando o ZIP…")
        resposta = self._abrir(
            urljoin(url_agenda, html_lib.unescape(alvo.group(1))),
            _campos_formulario(formulario),
            referer=url_agenda,
            tempo=600,
        )
        disposicao = resposta.headers.get("Content-Disposition", "")
        sugerido = re.search(r'filename="?([^";]+)', disposicao)
        destino = pasta / nome_arquivo_zip(nome, sugerido.group(1) if sugerido else "processo.zip")
        with resposta, destino.open("wb") as arquivo:
            shutil.copyfileobj(resposta, arquivo, 1024 * 1024)
        with destino.open("rb") as arquivo:
            cabecalho = arquivo.read(4)
        valido = destino.stat().st_size >= 100 and (
            cabecalho.startswith(b"%PDF") or (cabecalho.startswith(b"PK") and zipfile.is_zipfile(destino))
        )
        if not valido:
            destino.unlink(missing_ok=True)
            raise ConsultaInterrompida("O arquivo do processo veio vazio ou inválido.")
        return destino

    def _abrir_processo(self, numero: str) -> tuple[str, str]:
        if self._tela_busca is None and not self.logado():
            raise SessaoExpirada("A sessão do eproc expirou.")
        assert self._tela_busca is not None
        url, texto = self._tela_busca
        formulario = _formulario(texto, "formPesquisaRapida")
        campos = [
            (nome, valor)
            for nome, valor in _campos_formulario(formulario)
            if nome != _CAMPO_BUSCA
        ]
        campos.append((_CAMPO_BUSCA, numero))
        botao = formulario.xpath(".//button[@name='btnPesquisaRapidaSubmit']")
        if botao:
            campos.append(("btnPesquisaRapidaSubmit", botao[0].get("value") or ""))
        destino, pagina = self._ler(urljoin(url, formulario.get("action") or ""), campos)
        if acao_da_url(destino) != "processo_selecionar" or "infraEventoDescricao" not in pagina:
            raise ConsultaInterrompida(
                f"O eproc não abriu o processo {numero}. Confira o número."
            )
        if _CAMPO_BUSCA in pagina:
            self._tela_busca = (destino, pagina)
        return destino, pagina

    def _partes_ocultas(self, url: str, pagina: str) -> str:
        """'e outros' só busca o restante das partes. Não movimenta o processo."""
        ajax = re.search(
            r"""url\s*:\s*['"](controlador_ajax\.php\?acao_ajax=carregar_partes_ocultas_processo[^'"]+)['"]""",
            pagina,
        )
        chamadas = re.findall(
            r"carregarPartes\(\s*'(\d+)'\s*,\s*'(\d+)'\s*,\s*'(\w+)'\s*\)", pagina
        )
        if not ajax or not chamadas:
            return ""
        endereco = urljoin(url, html_lib.unescape(ajax.group(1)))
        fragmentos: list[str] = []
        for id_processo, id_pessoa, tipo in list(dict.fromkeys(chamadas))[:6]:
            try:
                _, corpo, tipo_resposta = self._pedir(
                    endereco,
                    [
                        ("idProcesso", id_processo),
                        ("idPessoaCarregada", id_pessoa),
                        ("tipoParte", tipo),
                        ("sinPermiteConsultaReuSobMonitoramento", "N"),
                        ("sinPermiteCadastroReuSobMonitoramento", "N"),
                    ],
                    referer=url,
                )
            except SessaoExpirada:
                raise
            except ConsultaInterrompida:
                logger.info("Não deu para abrir o restante das partes")
                continue
            texto = _decodificar(corpo, tipo_resposta)
            if texto.lstrip().startswith('"'):
                try:
                    texto = json.loads(texto)
                except json.JSONDecodeError:
                    pass
            fragmentos.append(texto)
        return "".join(fragmentos)

    def _url_processo(self) -> str:
        return self._processo[0] if self._processo else self._base

    def _ler(self, url: str, dados: list[tuple[str, str]] | None = None) -> tuple[str, str]:
        final, corpo, tipo = self._pedir(url, dados)
        texto = _decodificar(corpo, tipo)
        if _CAMPO_LOGIN in texto and _CAMPO_BUSCA not in texto:
            raise SessaoExpirada("A sessão do eproc expirou.")
        return final, texto

    def _pedir(
        self, url: str, dados: list[tuple[str, str]] | None = None, *, referer: str = ""
    ) -> tuple[str, bytes, str]:
        with self._abrir(url, dados, referer=referer) as resposta:
            corpo = resposta.read()
            return resposta.geturl(), corpo, resposta.headers.get("Content-Type", "").lower()

    def _abrir(
        self,
        url: str,
        dados: list[tuple[str, str]] | None = None,
        *,
        referer: str = "",
        tempo: int = 120,
    ):
        metodo = "POST" if dados is not None else "GET"
        if not pedido_http_permitido(metodo, url):
            raise ConsultaInterrompida(
                f"Bloqueei a ação '{acao_da_url(url) or url}', que não é consulta nem download."
            )
        corpo = (
            urlencode(dados, encoding="iso-8859-1", errors="replace").encode("ascii")
            if dados is not None
            else None
        )
        pedido = Request(url, data=corpo, method=metodo)
        pedido.add_header("User-Agent", _AGENTE)
        pedido.add_header("Accept-Language", "pt-BR,pt;q=0.9")
        pedido.add_header("Referer", referer or self._url_processo())
        if corpo is not None:
            pedido.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            return self._abridor.open(pedido, timeout=tempo)
        except HTTPError as erro:
            raise ConsultaInterrompida(
                f"O eproc respondeu HTTP {erro.code} em '{acao_da_url(url) or 'página inicial'}'."
            ) from erro
        except URLError as erro:
            raise ConsultaInterrompida(f"Não consegui falar com o eproc ({erro.reason}).") from erro


def cookies_do_navegador(cookies: list[dict]) -> list[dict]:
    return [dados for dados in cookies if dados.get("domain", "").lstrip(".") in _HOSTS]


def salvar_cookies(cookies: list[dict]) -> None:
    _COOKIES.parent.mkdir(parents=True, exist_ok=True)
    _COOKIES.write_text(json.dumps(cookies_do_navegador(cookies)), encoding="utf-8")


def _cookie(dados: dict) -> Cookie:
    dominio = dados["domain"]
    expira = dados.get("expires", -1)
    return Cookie(
        version=0,
        name=dados["name"],
        value=dados["value"],
        port=None,
        port_specified=False,
        domain=dominio,
        domain_specified=dominio.startswith("."),
        domain_initial_dot=dominio.startswith("."),
        path=dados.get("path") or "/",
        path_specified=True,
        secure=bool(dados.get("secure")),
        expires=int(expira) if expira and expira > 0 else None,
        discard=not (expira and expira > 0),
        comment=None,
        comment_url=None,
        rest={},
    )


def _decodificar(corpo: bytes, tipo: str) -> str:
    charset = re.search(r"charset=([\w-]+)", tipo)
    try:
        return corpo.decode(charset.group(1) if charset else "iso-8859-1", errors="replace")
    except LookupError:
        return corpo.decode("iso-8859-1", errors="replace")


def _formulario(pagina: str, id_formulario: str):
    formularios = lxml_html.fromstring(pagina).xpath(f"//form[@id='{id_formulario}']")
    if not formularios:
        raise ConsultaInterrompida(
            "O eproc mostrou uma tela que não está prevista. Me diga como seguir."
        )
    return formularios[0]


def _campos_formulario(formulario) -> list[tuple[str, str]]:
    """O que o navegador enviaria ao clicar no botão, sem marcar nada a mais."""
    campos: list[tuple[str, str]] = []
    for campo in formulario.xpath(".//input[@name]|.//select[@name]|.//textarea[@name]"):
        if campo.get("disabled") is not None:
            continue
        tipo = (campo.get("type") or "").lower()
        if campo.tag == "input" and tipo in ("submit", "button", "image", "file", "reset"):
            continue
        if campo.tag == "input" and tipo in ("checkbox", "radio") and campo.get("checked") is None:
            continue
        if campo.tag == "select":
            opcoes = campo.xpath(".//option[@selected]") or campo.xpath(".//option")
            valor = (opcoes[0].get("value") if opcoes else "") or ""
        elif campo.tag == "textarea":
            valor = campo.text or ""
        else:
            valor = campo.get("value") or ("on" if tipo in ("checkbox", "radio") else "")
        campos.append((campo.get("name"), valor))
    return campos


def _html_para_pdf(origem: Path, destino: Path) -> bool:
    """Imprime o HTML com o Chrome, fora da tela. Devolve False se não der."""
    from ferramentas.eproc.sessao import _CHROMES

    chrome = next((caminho for caminho in _CHROMES if caminho.is_file()), None)
    if chrome is None:
        return False
    perfil = Path(tempfile.mkdtemp(prefix="chrome-pdf-"))
    try:
        subprocess.run(
            [
                str(chrome),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-pdf-header-footer",
                f"--user-data-dir={perfil}",
                f"--print-to-pdf={destino.resolve()}",
                origem.resolve().as_uri(),
            ],
            capture_output=True,
            timeout=90,
            check=False,
        )
        valido = (
            destino.is_file()
            and destino.stat().st_size >= 100
            and destino.read_bytes()[:4] == b"%PDF"
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.info("Não deu para converter o HTML em PDF")
        valido = False
    finally:
        shutil.rmtree(perfil, ignore_errors=True)
    if not valido:
        destino.unlink(missing_ok=True)
    return valido


def _zip_pronto(agenda: str) -> bool:
    return 'name="btnBaixarTodos"' in agenda and "zip=S" in agenda


def _proximo_documento(pagina: str) -> str:
    brutos = re.findall(r"""<iframe\b[^>]*\bsrc\s*=\s*["']([^"']+)["']""", pagina, flags=re.I)
    brutos.extend(re.findall(r"""url\s*:\s*["']([^"']+)["']""", pagina, flags=re.I))
    validos: list[str] = []
    for href in brutos:
        href = html_lib.unescape(href)
        if href_documento(href) and href not in validos:
            validos.append(href)
    implementacoes = [href for href in validos if "implementacao" in href]
    if len(implementacoes) == 1:
        return implementacoes[0]
    if len(validos) == 1:
        return validos[0]
    return ""
