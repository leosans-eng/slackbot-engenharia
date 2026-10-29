"""Abre o eproc no Chrome, consulta processos e baixa só os PDFs previstos."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

from playwright.sync_api import Page, sync_playwright

from ferramentas.eproc.leitura import (
    Alvo,
    ConsultaInterrompida,
    LeituraProcesso,
    caminho_destino,
    ler_processo,
    mensagem_processo,
    nome_arquivo,
)
from ferramentas.eproc.seguranca import (
    acao_da_url,
    acao_de_escrita,
    host_permitido,
    href_documento,
    post_permitido,
)

logger = logging.getLogger(__name__)

_RAIZ = Path(__file__).resolve().parents[2]
_PERFIL = _RAIZ / "tmp" / "chrome-eproc"
_PORTA = 9333
_CHROMES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)


@dataclass
class ResultadoConsulta:
    nome: str
    numero: str
    texto: str
    arquivos: list[Path] = field(default_factory=list)


class SessaoEproc:
    """Uma janela de Chrome. Encerra ao sair, mesmo se a consulta parar."""

    def __init__(self, progresso) -> None:
        self._progresso = progresso
        self._playwright = None
        self._processo: subprocess.Popen | None = None
        self._pagina: Page | None = None
        self._bloqueada: str | None = None
        self._host_2fa = ""

    def __enter__(self) -> SessaoEproc:
        self._abrir()
        self._entrar()
        return self

    def __exit__(self, *_) -> None:
        self._fechar()

    def consultar(self, alvo: Alvo, pasta: Path) -> ResultadoConsulta:
        self._checar_bloqueio()
        self._progresso(f"Abrindo {alvo.nome.title()}…")
        self._abrir_processo(alvo.numero)
        assert self._pagina is not None
        leitura = ler_processo(self._pagina.content(), alvo.numero)
        self._progresso(f"Baixando documentos de {alvo.nome.title()}…")
        arquivos = self._baixar(leitura, alvo.nome, pasta)
        texto = mensagem_processo(alvo.nome, leitura)
        htmls = [arquivo.name for arquivo in arquivos if arquivo.suffix.lower() == ".html"]
        if htmls:
            texto += (
                "\n\nPublicado em HTML pelo eproc: " + ", ".join(f"`{nome}`" for nome in htmls)
            )
        return ResultadoConsulta(
            nome=alvo.nome,
            numero=alvo.numero,
            texto=texto,
            arquivos=arquivos,
        )

    def _abrir(self) -> None:
        chrome = next((caminho for caminho in _CHROMES if caminho.is_file()), None)
        if chrome is None:
            raise ConsultaInterrompida(
                "Não achei o Chrome nem o Edge neste computador. Nada foi peticionado."
            )
        _PERFIL.mkdir(parents=True, exist_ok=True)
        _encerrar_pid_anterior()
        self._progresso("Abrindo o Chrome para consultar o eproc…")
        self._processo = subprocess.Popen(
            [
                str(chrome),
                f"--user-data-dir={_PERFIL}",
                f"--remote-debugging-port={_PORTA}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        (_PERFIL / "bot.pid").write_text(str(self._processo.pid), encoding="utf-8")
        _esperar_porta()
        self._playwright = sync_playwright().start()
        navegador = self._playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{_PORTA}")
        contexto = navegador.contexts[0]
        self._pagina = contexto.pages[0] if contexto.pages else contexto.new_page()
        self._pagina.on(
            "dialog",
            lambda dialogo: (logger.info("Aviso do eproc: %s", dialogo.message), dialogo.accept()),
        )
        self._host_2fa = urlparse(_url_2fa()).hostname or ""
        self._pagina.route("**/*", self._filtrar)

    def _fechar(self) -> None:
        if self._pagina is not None:
            try:
                self._pagina.context.close()
            except Exception:
                pass
            self._pagina = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                logger.exception("Falha ao encerrar o Playwright")
            self._playwright = None
        if self._processo is not None:
            _matar(self._processo.pid)
            self._processo = None
        pid = _PERFIL / "bot.pid"
        if pid.exists():
            pid.unlink(missing_ok=True)

    def _filtrar(self, route) -> None:
        url = route.request.url
        if not host_permitido(url, self._host_2fa):
            route.abort()
            return
        acao = acao_da_url(url)
        if acao_de_escrita(acao):
            # Menu e prefetch em GET não são clique nosso. Navegação e POST, sim.
            if route.request.method.upper() != "GET" or route.request.resource_type == "document":
                self._bloqueada = acao
                logger.warning("Bloqueada ação de escrita no eproc: %s", acao)
            route.abort()
            return
        if route.request.method.upper() != "GET" and not post_permitido(url, self._host_2fa):
            # Ajax que a própria página dispara (lembretes, preferências) pode seguir.
            # Navegação POST para uma tela não prevista, não.
            if route.request.resource_type == "document":
                self._bloqueada = acao or "post"
                logger.warning("Bloqueada navegação POST não prevista: %s", acao or "post")
                route.abort()
                return
        route.continue_()

    def _checar_bloqueio(self) -> None:
        if self._bloqueada:
            acao = self._bloqueada
            self._bloqueada = None
            raise ConsultaInterrompida(
                f"Bloqueei a ação '{acao}', que não é consulta nem download. "
                "Nada foi peticionado."
            )

    def _entrar(self) -> None:
        pagina = self._exigir_pagina()
        base = _env("EPROC_BASE_URL", "https://eproc.jfrj.jus.br/eproc/").rstrip("/") + "/"
        pagina.goto(base, wait_until="domcontentloaded", timeout=60000)
        self._checar_bloqueio()
        if self._logado():
            return
        if self._tela() == "login":
            self._progresso("Entrando com o usuário do eproc…")
            pagina.fill("#txtUsuario", _env("EPROC_USER"))
            pagina.fill("#pwdSenha", _env("EPROC_PASS"))
            pagina.click("#sbmEntrar")
            pagina.wait_for_timeout(2000)
        if self._tela() == "captcha":
            self._resolver_captcha()
        if self._tela() == "2fa":
            self._validar_2fa()
        if not self._logado():
            raise ConsultaInterrompida(self._tela_imprevista())

    def _resolver_captcha(self) -> None:
        pagina = self._exigir_pagina()
        self._progresso(
            "O eproc pediu para confirmar que é humano. "
            "Se a caixa não marcar sozinha, clique nela na janela do Chrome."
        )
        self._clicar_captcha()
        if not self._esperar_captcha(20):
            self._esperar_captcha(90)
        if not self._token_captcha():
            raise ConsultaInterrompida(
                "O eproc pediu 'Confirme que é humano' e a confirmação não concluiu. "
                "Nada foi peticionado. Rode de novo e, se a janela abrir, marque a caixa."
            )
        pagina.evaluate(
            """() => {
                window.bolCloudflareSucess = true;
                const hidden = document.getElementById('hdnInfraCaptcha');
                if (hidden) hidden.value = '1';
            }"""
        )
        pagina.locator("button:has-text('Enviar')").first.click()
        pagina.wait_for_timeout(2500)
        self._checar_bloqueio()

    def _clicar_captcha(self) -> None:
        pagina = self._exigir_pagina()
        desafio = next(
            (frame for frame in pagina.frames if "challenges.cloudflare.com" in frame.url),
            None,
        )
        if desafio is None:
            return
        caixa = desafio.locator("body").bounding_box()
        if not caixa:
            return
        pagina.mouse.click(caixa["x"] + 22, caixa["y"] + caixa["height"] / 2)

    def _esperar_captcha(self, segundos: int) -> bool:
        pagina = self._exigir_pagina()
        for _ in range(segundos):
            if self._token_captcha():
                return True
            pagina.wait_for_timeout(1000)
        return False

    def _token_captcha(self) -> bool:
        pagina = self._exigir_pagina()
        tamanho = pagina.evaluate(
            """() => {
                const campo = document.querySelector("[name='cf-turnstile-response']");
                return campo && campo.value ? campo.value.length : 0;
            }"""
        )
        return bool(tamanho)

    def _validar_2fa(self) -> None:
        pagina = self._exigir_pagina()
        botao = pagina.locator("#btnValidar")
        if botao.count() == 0 or botao.inner_text().strip().casefold() != "validar":
            raise ConsultaInterrompida(self._tela_imprevista())
        for tentativa in (1, 2):
            self._progresso("Buscando o código de 2FA do advogado…")
            codigo = self._codigo_2fa()
            pagina.fill("#txtAcessoCodigo", codigo)
            if pagina.locator("#chkLiberarDispositivo").count():
                pagina.check("#chkLiberarDispositivo")
            botao.click()
            pagina.wait_for_timeout(3000)
            self._checar_bloqueio()
            if self._tela() != "2fa":
                return
            logger.info("2FA não aceito na tentativa %s", tentativa)
        erro = ""
        if pagina.locator("#divErro").count() and pagina.locator("#divErro").is_visible():
            erro = pagina.locator("#divErro").inner_text().strip()
        raise ConsultaInterrompida(
            "O eproc não aceitou o código de 2FA. Nada foi peticionado. "
            + (erro or "Confira o autenticador e tente de novo.")
        )

    def _codigo_2fa(self) -> str:
        pagina = self._exigir_pagina()
        guia = pagina.context.new_page()
        try:
            guia.route("**/*", self._filtrar)
            guia.goto(_url_2fa(), wait_until="domcontentloaded", timeout=60000)
            advogado = _env("EPROC_2FA_ADVOGADO")
            tribunal = _env("EPROC_TRIBUNAL", "") or _env("EPROC_2FA_TRIBUNAL", "TRF 2")
            guia.select_option("#ddlAdvogado", advogado)
            guia.wait_for_function(
                "() => document.querySelectorAll('#ddlTribunal option').length > 1",
                timeout=20000,
            )
            opcoes = [
                texto.strip()
                for texto in guia.locator("#ddlTribunal option").all_inner_texts()
                if texto.strip() and texto.strip().upper() != "SELECIONE"
            ]
            escolhido = next(
                (opcao for opcao in opcoes if opcao.casefold() == tribunal.casefold()),
                None,
            )
            if escolhido is None:
                escolhido = next(
                    (opcao for opcao in opcoes if tribunal.casefold() in opcao.casefold()),
                    None,
                )
            if escolhido is None:
                raise ConsultaInterrompida(
                    f"Não achei o tribunal '{tribunal}' no autenticador. "
                    "Nada foi peticionado."
                )
            guia.select_option("#ddlTribunal", label=escolhido)
            guia.wait_for_function(
                """() => {
                    const el = document.querySelector('#lblCodigo');
                    return el && /^\\d{6}$/.test((el.textContent || '').trim());
                }""",
                timeout=20000,
            )
            codigo = guia.locator("#lblCodigo").inner_text().strip()
        finally:
            guia.close()
        if len(codigo) != 6 or not codigo.isdigit():
            raise ConsultaInterrompida(
                "O autenticador não mostrou um código de 6 dígitos. Nada foi peticionado."
            )
        return codigo

    def _abrir_processo(self, numero: str) -> None:
        pagina = self._exigir_pagina()
        if not self._logado():
            raise ConsultaInterrompida(self._tela_imprevista())
        pagina.locator("#txtNumProcessoPesquisaRapida").first.fill(numero)
        pagina.locator("#formPesquisaRapida button").first.click()
        try:
            pagina.wait_for_function(
                "() => location.href.includes('acao=processo_selecionar')",
                timeout=60000,
            )
        except Exception as erro:
            raise ConsultaInterrompida(self._tela_imprevista()) from erro
        self._checar_bloqueio()
        if "acao=processo_selecionar" not in pagina.url:
            raise ConsultaInterrompida(self._tela_imprevista())
        try:
            pagina.wait_for_selector("td.infraEventoDescricao", timeout=60000)
        except Exception as erro:
            raise ConsultaInterrompida(self._tela_imprevista()) from erro
        try:
            pagina.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

    def _baixar(self, leitura: LeituraProcesso, nome: str, pasta: Path) -> list[Path]:
        arquivos: list[Path] = []
        if leitura.laudo:
            arquivos.extend(
                self._baixar_evento(leitura.laudo.documentos, "laudo", nome, pasta)
            )
        if leitura.despacho:
            arquivos.extend(
                self._baixar_evento(leitura.despacho.documentos, "despacho", nome, pasta)
            )
        return arquivos

    def _baixar_evento(self, documentos, prefixo: str, nome: str, pasta: Path) -> list[Path]:
        if len(documentos) > 8:
            raise ConsultaInterrompida(
                f"O evento tem {len(documentos)} documentos, mais do que o previsto. "
                "Parei antes de baixar. Nada foi peticionado."
            )
        salvos: list[Path] = []
        for indice, documento in enumerate(documentos, start=1):
            destino = caminho_destino(
                pasta,
                nome_arquivo(prefixo, nome, indice, len(documentos)),
            )
            salvos.append(self._baixar_pdf(documento.href, destino))
        return salvos

    def _baixar_pdf(self, href: str, destino: Path, salto: int = 0) -> Path:
        if not href_documento(href):
            raise ConsultaInterrompida(
                "O link do documento não é só de leitura. Nada foi baixado além do previsto."
            )
        pagina = self._exigir_pagina()
        resposta = pagina.request.get(urljoin(pagina.url, href), timeout=120000)
        self._checar_bloqueio()
        if not resposta.ok:
            raise ConsultaInterrompida(
                f"O documento não baixou (HTTP {resposta.status}). Nada foi peticionado."
            )
        corpo = resposta.body()
        tipo = (resposta.headers.get("content-type") or "").lower()
        parece_html = corpo[:200].lstrip().lower().startswith((b"<", b"<!"))
        parece_pdf = corpo.startswith(b"%PDF") or ("pdf" in tipo and not parece_html)
        if parece_pdf:
            if len(corpo) < 100:
                raise ConsultaInterrompida(
                    "O arquivo do documento veio vazio. Nada foi peticionado."
                )
            destino.write_bytes(corpo)
            return destino
        texto = corpo.decode("latin-1", errors="replace")
        proximo = _proximo_documento(texto) if salto < 2 else ""
        if proximo and proximo != href:
            return self._baixar_pdf(proximo, destino, salto=salto + 1)
        if salto >= 1 and texto.strip():
            arquivo = destino.with_suffix(".html")
            arquivo.write_text(texto, encoding="utf-8")
            return arquivo
        raise ConsultaInterrompida(
            "O eproc não devolveu o PDF do documento. Parei para não abrir outra tela. "
            "Nada foi peticionado."
        )

    def _logado(self) -> bool:
        pagina = self._exigir_pagina()
        campo = pagina.locator("#txtNumProcessoPesquisaRapida")
        return campo.count() > 0 and campo.first.is_visible()

    def _tela(self) -> str:
        pagina = self._exigir_pagina()
        if self._logado():
            return "processo"
        codigo = pagina.locator("#txtAcessoCodigo")
        if codigo.count() and codigo.is_visible():
            return "2fa"
        usuario = pagina.locator("#txtUsuario")
        if usuario.count() and usuario.is_visible():
            return "login"
        if pagina.locator("#divInfraCaptcha, .cf-turnstile").count():
            return "captcha"
        return "outra"

    def _tela_imprevista(self) -> str:
        pagina = self._exigir_pagina()
        titulo = pagina.title() or "sem título"
        acao = acao_da_url(pagina.url) or "página inicial"
        return (
            f"Parei numa tela que não está prevista ({titulo}, ação {acao}). "
            "Nada foi peticionado. Me diga como seguir antes de eu clicar em qualquer coisa."
        )

    def _exigir_pagina(self) -> Page:
        if self._pagina is None:
            raise ConsultaInterrompida("O Chrome fechou antes da consulta. Nada foi peticionado.")
        return self._pagina


def consultar_processos(alvos: list[Alvo], pasta: Path, progresso=None) -> list[ResultadoConsulta]:
    """Consulta cada processo na mesma sessão. Para no primeiro imprevisto."""
    aviso = progresso or (lambda _texto: None)
    if not alvos:
        raise ValueError("Nenhum processo para consultar.")
    pasta.mkdir(parents=True, exist_ok=True)
    with SessaoEproc(aviso) as sessao:
        return [sessao.consultar(alvo, pasta) for alvo in alvos]


def _env(nome: str, padrao: str | None = None) -> str:
    valor = os.environ.get(nome, "")
    if not valor and nome == "EPROC_TRIBUNAL":
        valor = os.environ.get("EPROC_2FA_TRIBUNAL", "")
    if valor:
        return valor
    if padrao is not None:
        return padrao
    raise ConsultaInterrompida(
        f"Falta {nome} no .env. Nada foi peticionado."
    )


def _url_2fa() -> str:
    url = os.environ.get("2FA_URL") or os.environ.get("2FA_url") or ""
    partes = urlparse(url)
    if partes.scheme != "https" or "autenticador" not in (partes.path or "").lower():
        raise ConsultaInterrompida(
            "2FA_URL precisa ser o autenticador em https. Nada foi peticionado."
        )
    return url


def _proximo_documento(html: str) -> str:
    import html as html_lib
    import re

    brutos = re.findall(
        r"""<iframe\b[^>]*\bsrc\s*=\s*["']([^"']+)["']""",
        html,
        flags=re.I,
    )
    brutos.extend(
        re.findall(r"""url\s*:\s*["']([^"']+)["']""", html, flags=re.I)
    )
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


def _esperar_porta() -> None:
    for _ in range(40):
        try:
            with urlopen(f"http://127.0.0.1:{_PORTA}/json/version", timeout=1):
                return
        except Exception:
            time.sleep(0.5)
    raise ConsultaInterrompida(
        "O Chrome não abriu a tempo. Nada foi peticionado."
    )


def _encerrar_pid_anterior() -> None:
    arquivo = _PERFIL / "bot.pid"
    if not arquivo.exists():
        return
    try:
        pid = int(arquivo.read_text(encoding="utf-8").strip())
    except ValueError:
        return
    _matar(pid)


def _matar(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        check=False,
    )
