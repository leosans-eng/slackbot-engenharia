"""Consulta o eproc por HTTP. O Chrome só abre, fora da tela, para entrar de novo."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import Page, sync_playwright

from ferramentas.eproc.cliente_http import ClienteEproc, SessaoExpirada, salvar_cookies
from ferramentas.eproc.leitura import (
    Alvo,
    ConsultaInterrompida,
    LeituraProcesso,
    caminho_destino,
    mensagem_processo,
    nome_arquivo,
    tribunal_do_cnj,
)
from ferramentas.eproc.seguranca import (
    acao_da_url,
    acao_de_escrita,
    host_permitido,
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
    """Consulta por HTTP. Se a sessão morreu, entra pelo Chrome e fecha a janela em seguida."""

    def __init__(self, progresso) -> None:
        self._progresso = progresso
        self._playwright = None
        self._processo: subprocess.Popen | None = None
        self._pagina: Page | None = None
        self._bloqueada: str | None = None
        self._host_2fa = ""
        self._base = _env("EPROC_BASE_URL", "https://eproc.jfrj.jus.br/eproc/").rstrip("/") + "/"
        self._cliente: ClienteEproc | None = None

    def __enter__(self) -> SessaoEproc:
        cliente = ClienteEproc.carregar(self._base)
        if cliente is not None and cliente.logado():
            self._cliente = cliente
        else:
            self._entrar_pelo_navegador()
        return self

    def __exit__(self, *_) -> None:
        self._fechar()
        if self._cliente is not None:
            self._cliente.salvar()

    def consultar(self, alvo: Alvo, pasta: Path, *, completo: bool = False) -> ResultadoConsulta:
        try:
            return self._consultar(alvo, pasta, completo)
        except SessaoExpirada:
            self._progresso("A sessão do eproc expirou. Entrando de novo…")
            self._entrar_pelo_navegador()
            return self._consultar(alvo, pasta, completo)

    def _entrar_pelo_navegador(self) -> None:
        try:
            self._abrir()
            self._entrar()
            cookies = self._exigir_pagina().context.cookies()
        finally:
            self._fechar()
        salvar_cookies(cookies)
        cliente = ClienteEproc.carregar(self._base)
        if cliente is None or not cliente.logado():
            raise ConsultaInterrompida(
                "Entrei no eproc, mas a sessão não valeu fora do navegador. Tente de novo."
            )
        self._cliente = cliente

    def _consultar(self, alvo: Alvo, pasta: Path, completo: bool) -> ResultadoConsulta:
        cliente = self._exigir_cliente()
        rotulo = alvo.nome.strip().title() if alvo.nome.strip() else alvo.numero
        tribunal = tribunal_do_cnj(alvo.numero)
        onde = f" no {tribunal.sigla}" if tribunal else ""
        self._progresso(f"Abrindo {rotulo}{onde}…")
        leitura = cliente.ler(alvo.numero)
        texto = mensagem_processo(alvo.nome, leitura, vara=alvo.vara)
        if completo:
            self._progresso(f"Baixando o processo completo de {rotulo}…")
            arquivos = [cliente.baixar_completo(pasta, alvo.nome_arquivo, self._progresso)]
            texto += "\n\n*Processo na íntegra*\nZIP com as partes do processo."
        else:
            self._progresso(f"Baixando laudo e despacho de {rotulo}…")
            arquivos = self._baixar(leitura, alvo.nome_arquivo, pasta)
            htmls = [arquivo.name for arquivo in arquivos if arquivo.suffix.lower() == ".html"]
            if htmls:
                texto += (
                    "\n\nPublicado em HTML: " + ", ".join(f"`{nome}`" for nome in htmls)
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
                "Não achei o Chrome nem o Edge neste computador."
            )
        _PERFIL.mkdir(parents=True, exist_ok=True)
        _encerrar_pid_anterior()
        self._progresso("Entrando no eproc…")
        self._processo = subprocess.Popen(
            [
                str(chrome),
                f"--user-data-dir={_PERFIL}",
                f"--remote-debugging-port={_PORTA}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                # Fora da tela, não headless: o login passa pelo Turnstile do Cloudflare.
                "--window-position=-32000,-32000",
                "--disable-features=CalculateNativeWinOcclusion",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
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
        contexto.route("**/*", self._filtrar)

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
                f"Bloqueei a ação '{acao}', que não é consulta nem download."
            )

    def _entrar(self) -> None:
        pagina = self._exigir_pagina()
        pagina.goto(self._base, wait_until="domcontentloaded", timeout=60000)
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
        self._clicar_captcha()
        if not self._esperar_captcha(20):
            self._mostrar_janela()
            self._progresso(
                "O eproc pediu para confirmar que é humano e a caixa não marcou sozinha. "
                "Abri a janela do Chrome: marque a caixa."
            )
            self._esperar_captcha(90)
        if not self._token_captcha():
            raise ConsultaInterrompida(
                "O eproc pediu 'Confirme que é humano' e a confirmação não concluiu. "
                "Rode de novo e, se a janela abrir, marque a caixa."
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

    def _mostrar_janela(self) -> None:
        pagina = self._exigir_pagina()
        try:
            cdp = pagina.context.new_cdp_session(pagina)
            janela = cdp.send("Browser.getWindowForTarget")
            cdp.send(
                "Browser.setWindowBounds",
                {
                    "windowId": janela["windowId"],
                    "bounds": {"left": 80, "top": 60, "width": 1200, "height": 850},
                },
            )
        except Exception:
            logger.exception("Não deu para trazer a janela do Chrome para a tela")

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
            "O eproc não aceitou o código de 2FA."
            + (erro or "Confira o autenticador e tente de novo.")
        )

    def _codigo_2fa(self) -> str:
        pagina = self._exigir_pagina()
        guia = pagina.context.new_page()
        try:
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
                "O autenticador não mostrou um código de 6 dígitos."
            )
        return codigo

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
                "Parei antes de baixar."
            )
        salvos: list[Path] = []
        for indice, documento in enumerate(documentos, start=1):
            destino = caminho_destino(
                pasta,
                nome_arquivo(prefixo, nome, indice, len(documentos)),
            )
            salvos.append(self._exigir_cliente().baixar_documento(documento.href, destino))
        return salvos

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
            "Me diga como seguir antes de eu clicar em qualquer coisa."
        )

    def _exigir_cliente(self) -> ClienteEproc:
        if self._cliente is None:
            raise ConsultaInterrompida("A sessão do eproc não abriu.")
        return self._cliente

    def _exigir_pagina(self) -> Page:
        if self._pagina is None:
            raise ConsultaInterrompida("O Chrome fechou antes da consulta.")
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
        f"Falta {nome} no .env."
    )


def _url_2fa() -> str:
    url = os.environ.get("2FA_URL") or os.environ.get("2FA_url") or ""
    partes = urlparse(url)
    if partes.scheme != "https" or "autenticador" not in (partes.path or "").lower():
        raise ConsultaInterrompida(
            "2FA_URL precisa ser o autenticador em https."
        )
    return url


def _esperar_porta() -> None:
    for _ in range(40):
        try:
            with urlopen(f"http://127.0.0.1:{_PORTA}/json/version", timeout=1):
                return
        except Exception:
            time.sleep(0.5)
    raise ConsultaInterrompida(
        "O Chrome não abriu a tempo."
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
