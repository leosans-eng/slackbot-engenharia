"""Automação UI do Infobase CP MCMV: login → Exportar p/ Excel → capturar arquivo.

O Excel embutido do CP é 32-bit; Python 64-bit em geral não vê os workbooks
via COM. Por isso a captura usa a janela do Excel + Salvar como (F12).
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

from ferramentas.idebras.config import CP_EXE, require_cp_credentials

logger = logging.getLogger(__name__)

LOGIN_TIMEOUT = 90
EXPORT_TIMEOUT = 90


def _escape_send_keys(text: str) -> str:
    return (
        text.replace("{", "{{")
        .replace("}", "}}")
        .replace("+", "{+}")
        .replace("^", "{^}")
        .replace("%", "{%}")
        .replace("~", "{~}")
        .replace("(", "{(}")
        .replace(")", "{)}")
    )


def _nome_processo(pid: int) -> str:
    """Nome do executável do PID (funciona 32/64-bit via QueryFullProcessImageName)."""
    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
            if ok:
                return Path(buf.value).name.lower()
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        pass
    return ""


def _foreground_eh_infobase() -> bool:
    """True se a janela em primeiro plano pertence ao Infobase."""
    try:
        import win32gui
        import win32process

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return False
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        nome = _nome_processo(int(pid))
        esperado = {Path(CP_EXE).name.lower(), "infobase.exe"}
        return nome in esperado
    except Exception:
        return False


def _focar_janela(win) -> None:
    """Traz a janela do Infobase para o foco (sem digitar nada)."""
    import win32con
    import win32gui

    try:
        hwnd = int(win.handle)
    except Exception:
        try:
            win.set_focus()
        except Exception:
            pass
        time.sleep(0.35)
        return

    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    try:
        win.set_focus()
    except Exception:
        pass
    time.sleep(0.4)


def _janelas_visiveis(app) -> list:
    if app is None:
        return []
    try:
        return [w for w in app.windows() if w.is_visible()]
    except Exception:
        return []


def _garantir_foco_infobase(app, wins=None) -> None:
    """Foca o Infobase e aborta se outra janela (ex.: Slack) continuar no foco."""
    app = _find_running_infobase() or app
    atuais = _janelas_visiveis(app) or list(wins or [])
    if not atuais:
        raise RuntimeError("Nenhuma janela visível do Infobase para focar.")

    _focar_janela(atuais[0])
    if _foreground_eh_infobase():
        return

    time.sleep(0.3)
    _focar_janela(atuais[0])
    if _foreground_eh_infobase():
        return

    raise RuntimeError(
        "Não foi possível colocar o Infobase em primeiro plano. "
        "Por segurança, *nenhuma credencial foi digitada*. "
        "Feche ou minimize outras janelas (Slack, Excel, etc.) e tente de novo."
    )


def _type_and_enter(text: str) -> None:
    """Digita texto + Enter *somente* se o Infobase estiver em foco."""
    from pywinauto.keyboard import send_keys

    if not _foreground_eh_infobase():
        raise RuntimeError(
            "Foco saiu do Infobase antes de digitar. "
            "Por segurança, a digitação foi cancelada (credenciais não enviadas)."
        )

    send_keys("^a{BACKSPACE}")
    if not _foreground_eh_infobase():
        raise RuntimeError(
            "Foco saiu do Infobase durante a digitação. "
            "Por segurança, a operação foi cancelada."
        )
    send_keys(_escape_send_keys(text), with_spaces=True, pause=0.02)
    time.sleep(0.15)
    if not _foreground_eh_infobase():
        raise RuntimeError(
            "Foco saiu do Infobase antes do Enter. "
            "Por segurança, a operação foi cancelada."
        )
    send_keys("{ENTER}")


def _launch_infobase() -> None:
    if not CP_EXE.is_file():
        raise FileNotFoundError(
            f"Infobase não encontrado em {CP_EXE}. Ajuste CP_EXE no .env."
        )
    env = os.environ.copy()
    env["__COMPAT_LAYER"] = "RunAsInvoker"
    try:
        subprocess.Popen(
            [str(CP_EXE)],
            cwd=str(CP_EXE.parent),
            env=env,
            close_fds=True,
        )
    except OSError as exc:
        raise RuntimeError(
            f"Não foi possível abrir o Infobase: {exc}."
        ) from exc


def _find_running_infobase():
    from pywinauto import Application

    for path in (str(CP_EXE), "infobase.exe"):
        try:
            return Application(backend="win32").connect(path=path, timeout=2)
        except Exception:
            continue
    return None


def _wait_app_windows(timeout: float = LOGIN_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app = _find_running_infobase()
        if app is not None:
            try:
                wins = [w for w in app.windows() if w.is_visible()]
            except Exception:
                wins = []
            if wins:
                return app, wins
        time.sleep(0.4)
    raise RuntimeError("Janela do Infobase não apareceu (login).")


def _click_exportar(app) -> bool:
    for w in app.windows():
        try:
            for ctrl in w.descendants():
                try:
                    title = (ctrl.window_text() or "").strip()
                except Exception:
                    continue
                if "Exportar" in title and "Excel" in title:
                    try:
                        ctrl.click_input()
                    except Exception:
                        ctrl.click()
                    return True
        except Exception:
            continue
    return False


# Frases específicas do aviso real de atualização do CP (não usar "atualiza" solto:
# bate em botões normais como "Atualizar Lista").
_ATUALIZACAO_KEYWORDS = (
    "atualizar seu sistema",
    "precisa atualizar seu sistema",
    "arquivo de atualização",
    "arquivo de atualizacao",
    "execute o arquivo de atualização",
    "execute o arquivo de atualizacao",
    "pasta cp no geral",
    "você precisa atualizar",
    "voce precisa atualizar",
)


def _texto_parece_atualizacao(texto: str) -> bool:
    low = (texto or "").lower()
    return any(k in low for k in _ATUALIZACAO_KEYWORDS)


def _coletar_textos_janelas(app=None) -> list[str]:
    """Textos visíveis do Infobase e de diálogos top-level (MessageBox)."""
    textos: list[str] = []
    if app is not None:
        try:
            for w in app.windows():
                try:
                    t = (w.window_text() or "").strip()
                    if t:
                        textos.append(t)
                except Exception:
                    pass
                try:
                    for ctrl in w.descendants():
                        try:
                            t = (ctrl.window_text() or "").strip()
                            if t and len(t) < 500:
                                textos.append(t)
                        except Exception:
                            continue
                except Exception:
                    continue
        except Exception:
            pass

    try:
        import win32gui

        def _cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            try:
                title = win32gui.GetWindowText(hwnd) or ""
            except Exception:
                return True
            if title:
                textos.append(title)
            return True

        win32gui.EnumWindows(_cb, None)
    except Exception:
        pass

    return textos


def _detectar_dialogo_atualizacao(app=None) -> str | None:
    """Retorna trecho do texto se houver o aviso de atualização do sistema CP."""
    for texto in _coletar_textos_janelas(app):
        if _texto_parece_atualizacao(texto):
            return texto
    return None


MSG_ATUALIZACAO_CP = (
    "O CP Infobase exige *atualização do sistema*. "
    "Abra o CP manualmente, execute o arquivo de atualização (pasta CP no Geral) "
    "e tente `/fluxos-cp` de novo."
)


def _erro_se_atualizacao_ou_fechou(app, *, contexto: str) -> None:
    """Levanta RuntimeError claro se houver o aviso real de update do sistema."""
    aviso = _detectar_dialogo_atualizacao(app)
    if aviso:
        logger.warning("Diálogo de atualização detectado (%s): %r", contexto, aviso)
        raise RuntimeError(MSG_ATUALIZACAO_CP)

    ainda_aberto = _find_running_infobase() is not None
    if not ainda_aberto:
        logger.warning(
            "Infobase fechou durante %s — possível atualização ou falha de login.",
            contexto,
        )
        raise RuntimeError(
            "O Infobase fechou inesperadamente. "
            "Se pediu atualização, conclua-a e tente `/fluxos-cp` de novo."
        )


def _enum_excel_hwnds() -> list[tuple[int, str]]:
    """Janelas principais do Excel (classe XLMAIN)."""
    import win32gui

    found: list[tuple[int, str]] = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            cls = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd) or ""
        except Exception:
            return True
        if cls == "XLMAIN" or (
            "excel" in title.lower()
            and "infobase" not in title.lower()
            and win32gui.GetParent(hwnd) == 0
        ):
            found.append((hwnd, title))
        return True

    win32gui.EnumWindows(_cb, None)
    return found


def _wait_new_excel_window(
    before_hwnds: set[int],
    before_titles: dict[int, str],
    timeout: float = EXPORT_TIMEOUT,
) -> tuple[int, str]:
    """Espera janela Excel nova OU mudança de título (mesmo HWND reutilizado)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = _enum_excel_hwnds()
        for hwnd, title in current:
            if hwnd not in before_hwnds:
                return hwnd, title
            prev = before_titles.get(hwnd, "")
            if title and title != prev:
                low = title.lower()
                if any(
                    tip in low
                    for tip in (
                        "livro",
                        "book",
                        "planilha",
                        ".xls",
                        "microsoft excel",
                    )
                ):
                    return hwnd, title
        time.sleep(0.4)
    raise TimeoutError(
        "Janela do Excel não apareceu/atualizou após Exportar. "
        "Salve a planilha manualmente."
    )


def _focus_hwnd(hwnd: int) -> None:
    import win32con
    import win32gui

    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.3)


def _save_excel_via_dialog(hwnd: int, dest: Path) -> Path:
    """F12 (Salvar como) e grava em dest (.xlsx)."""
    from pywinauto.keyboard import send_keys
    import win32gui

    dest = dest.with_suffix(".xlsx")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        try:
            dest.unlink()
        except OSError:
            pass

    _focus_hwnd(hwnd)
    send_keys("{F12}")
    time.sleep(1.0)

    path_str = str(dest.resolve())
    send_keys("^a")
    time.sleep(0.1)
    send_keys(_escape_send_keys(path_str), with_spaces=True, pause=0.01)
    time.sleep(0.2)
    send_keys("{ENTER}")
    time.sleep(0.8)

    for _ in range(6):
        send_keys("{ENTER}")
        time.sleep(0.35)
        if dest.is_file() and dest.stat().st_size > 100:
            return dest

    if not dest.is_file():
        _focus_hwnd(hwnd)
        send_keys("%a")
        time.sleep(0.4)
        send_keys("a")
        time.sleep(0.8)
        send_keys("^a")
        send_keys(_escape_send_keys(path_str), with_spaces=True, pause=0.01)
        send_keys("{ENTER}")
        for _ in range(6):
            send_keys("{ENTER}")
            time.sleep(0.35)
            if dest.is_file() and dest.stat().st_size > 100:
                return dest

    if dest.is_file() and dest.stat().st_size > 100:
        return dest

    title = ""
    try:
        title = win32gui.GetWindowText(hwnd)
    except Exception:
        pass
    raise RuntimeError(
        f"Não conseguiu salvar a planilha via diálogo (janela: {title!r})."
    )


def _try_com_save(dest: Path, before_keys: set[str]) -> Path | None:
    """Tenta COM (só funciona se o Excel for da mesma arquitetura do Python)."""
    try:
        import win32com.client
    except ImportError:
        return None

    excel = None
    for getter in (
        lambda: win32com.client.GetActiveObject("Excel.Application"),
        lambda: win32com.client.GetObject(Class="Excel.Application"),
    ):
        try:
            excel = getter()
            break
        except Exception:
            continue
    if excel is None:
        return None

    try:
        count = int(excel.Workbooks.Count)
    except Exception:
        return None

    for i in range(1, count + 1):
        try:
            wb = excel.Workbooks(i)
            full = (wb.FullName or "").strip()
            name = (wb.Name or "").strip()
            key = full.lower() if full else f"unsaved:{name.lower()}"
            if key in before_keys and full:
                continue
            dest = dest.with_suffix(".xlsx")
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                wb.SaveCopyAs(str(dest))
            except Exception:
                wb.SaveAs(str(dest), FileFormat=51)
            if dest.is_file() and dest.stat().st_size > 100:
                return dest
        except Exception:
            continue
    return None


def _com_workbook_keys() -> set[str]:
    try:
        import win32com.client

        excel = win32com.client.GetActiveObject("Excel.Application")
    except Exception:
        return set()
    keys: set[str] = set()
    try:
        for i in range(1, int(excel.Workbooks.Count) + 1):
            wb = excel.Workbooks(i)
            full = (wb.FullName or "").strip()
            name = (wb.Name or "").strip()
            keys.add(full.lower() if full else f"unsaved:{name.lower()}")
    except Exception:
        pass
    return keys


def export_fluxos_via_ui(*, close_app: bool = False) -> Path:
    """Abre Infobase, autentica, exporta e grava .xlsx estável."""
    from pywinauto.keyboard import send_keys

    user, password = require_cp_credentials()
    if not CP_EXE.is_file():
        raise FileNotFoundError(
            f"Infobase não encontrado em {CP_EXE}. Ajuste CP_EXE no .env."
        )

    before_list = _enum_excel_hwnds()
    before_excel = {hwnd for hwnd, _ in before_list}
    before_titles = {hwnd: title for hwnd, title in before_list}
    before_com = _com_workbook_keys()

    app = _find_running_infobase()
    if app is None:
        logger.info("Abrindo Infobase...")
        _launch_infobase()
        app, wins = _wait_app_windows()
    else:
        logger.info("Infobase já aberto; reutilizando.")
        try:
            wins = [w for w in app.windows() if w.is_visible()]
        except Exception:
            wins = []

    if not wins:
        raise RuntimeError("Nenhuma janela visível do Infobase.")

    # Aguarda diálogos iniciais (ex.: atualização) antes de qualquer tecla
    time.sleep(1.0)
    app = _find_running_infobase() or app
    try:
        wins = [w for w in app.windows() if w.is_visible()] if app else wins
    except Exception:
        pass

    aviso = _detectar_dialogo_atualizacao(app)
    if aviso:
        logger.warning("Atualização do CP detectada antes do login: %r", aviso)
        raise RuntimeError(MSG_ATUALIZACAO_CP)

    if app is None or not wins:
        _erro_se_atualizacao_ou_fechou(None, contexto="antes do login")
        raise RuntimeError("Infobase fechou antes do login.")

    # Só digita credenciais com o Infobase comprovadamente em foco
    _garantir_foco_infobase(app, wins)

    logger.info("Login CP...")
    _type_and_enter(user)
    time.sleep(0.4)

    aviso = _detectar_dialogo_atualizacao(_find_running_infobase())
    if aviso:
        logger.warning("Atualização do CP detectada após usuário: %r", aviso)
        raise RuntimeError(MSG_ATUALIZACAO_CP)

    _garantir_foco_infobase(app, wins)
    _type_and_enter(password)
    time.sleep(0.6)

    aviso = _detectar_dialogo_atualizacao(_find_running_infobase())
    if aviso:
        logger.warning("Atualização do CP detectada após senha: %r", aviso)
        raise RuntimeError(MSG_ATUALIZACAO_CP)

    if _foreground_eh_infobase():
        send_keys("{ENTER}")
    time.sleep(0.8)
    _erro_se_atualizacao_ou_fechou(
        _find_running_infobase(),
        contexto="após login",
    )

    logger.info('Clicando em "Exportar p/ Excel"...')
    clicked = False
    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            app = _find_running_infobase() or app
            if app is None:
                _erro_se_atualizacao_ou_fechou(None, contexto="busca Exportar")
            aviso = _detectar_dialogo_atualizacao(app)
            if aviso:
                logger.warning("Diálogo de atualização durante Exportar: %r", aviso)
                raise RuntimeError(MSG_ATUALIZACAO_CP)
            if app and _click_exportar(app):
                clicked = True
                break
        except RuntimeError:
            raise
        except Exception:
            pass
        time.sleep(0.45)

    if not clicked:
        _erro_se_atualizacao_ou_fechou(
            _find_running_infobase(),
            contexto='antes de "Exportar p/ Excel"',
        )
        raise RuntimeError(
            'Não encontrou "Exportar p/ Excel" no Infobase. '
            "Se o CP pediu atualização, conclua-a manualmente e tente de novo."
        )

    stable = Path(tempfile.gettempdir()) / f"fluxos_cp_capture_{int(time.time())}.xlsx"

    logger.info("Aguardando Excel e salvando planilha...")
    com_saved = None
    com_deadline = time.time() + 2
    while time.time() < com_deadline:
        com_saved = _try_com_save(stable, before_com)
        if com_saved:
            logger.info("Planilha capturada (COM): %s", com_saved)
            break
        time.sleep(0.4)

    if not com_saved:
        hwnd, title = _wait_new_excel_window(before_excel, before_titles)
        logger.info("Excel detectado: %r", title)
        time.sleep(1.0)
        saved = _save_excel_via_dialog(hwnd, stable)
        logger.info("Planilha capturada: %s", saved)
        com_saved = saved

    if close_app and app is not None:
        try:
            app.kill()
        except Exception:
            pass

    return com_saved
