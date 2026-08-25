"""Cliente HTTP mínimo para ASP.NET Web Forms (sessão + ViewState)."""

from __future__ import annotations

import html as html_lib
import re
import uuid
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from ferramentas.idebras.config import BASE_URL, require_credentials

INPUT_TAG = re.compile(r"<input\b([^>]*)>", re.I)
SELECT_TAG = re.compile(r"<select\b([^>]*)>(.*?)</select>", re.I | re.S)
TEXTAREA_TAG = re.compile(r"<textarea\b([^>]*)>(.*?)</textarea>", re.I | re.S)
ATTR = re.compile(r"""([^\s=]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
PASSWORD_FIELD = re.compile(r'name=["\']txtsenha["\']', re.I)


def _attrs(tag_attrs: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in ATTR.finditer(tag_attrs):
        key = m.group(1).lower()
        val = m.group(2) if m.group(2) is not None else (
            m.group(3) if m.group(3) is not None else m.group(4) or ""
        )
        out[key] = html_lib.unescape(val)
    return out


def parse_hidden_fields(html: str) -> dict[str, str]:
    """Extrai inputs hidden do formulário (ViewState, EventValidation, etc.)."""
    out: dict[str, str] = {}
    for m in INPUT_TAG.finditer(html):
        a = _attrs(m.group(1))
        if a.get("type", "text").lower() != "hidden":
            continue
        name = a.get("name")
        if name:
            out[name] = a.get("value", "")
    return out


def parse_form_fields(html: str) -> dict[str, str]:
    """Extrai estado típico de form ASP.NET: hidden, text, checkbox marcados, selects, textarea."""
    fields: dict[str, str] = {}

    for m in INPUT_TAG.finditer(html):
        a = _attrs(m.group(1))
        name = a.get("name")
        if not name:
            continue
        typ = a.get("type", "text").lower()
        if typ in {"submit", "button", "image", "file", "reset"}:
            continue
        if typ in {"checkbox", "radio"}:
            if "checked" in a or a.get("checked") is not None:
                fields[name] = a.get("value", "on")
            continue
        if typ == "hidden" or typ in {
            "text",
            "password",
            "email",
            "search",
            "tel",
            "url",
            "number",
            "date",
            "",
        }:
            fields[name] = a.get("value", "")

    for m in INPUT_TAG.finditer(html):
        raw = m.group(1)
        a = _attrs(raw)
        name = a.get("name")
        typ = a.get("type", "text").lower()
        if not name or typ not in {"checkbox", "radio"}:
            continue
        if re.search(r"\bchecked\b", raw, re.I):
            fields[name] = a.get("value", "on")

    for m in SELECT_TAG.finditer(html):
        a = _attrs(m.group(1))
        name = a.get("name")
        if not name:
            continue
        body = m.group(2)
        selected = re.findall(
            r"<option\b([^>]*)>(.*?)</option>",
            body,
            flags=re.I | re.S,
        )
        value = ""
        for opt_attrs, _label in selected:
            oa = _attrs(opt_attrs)
            if re.search(r"\bselected\b", opt_attrs, re.I) or not value:
                value = oa.get("value", "")
                if re.search(r"\bselected\b", opt_attrs, re.I):
                    break
        fields[name] = value

    for m in TEXTAREA_TAG.finditer(html):
        a = _attrs(m.group(1))
        name = a.get("name")
        if name:
            fields[name] = html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()

    return fields


def parse_async_delta(text: str) -> dict[str, str]:
    """Extrai hiddenField / updates de resposta UpdatePanel (|len|type|id|content|)."""
    updates: dict[str, str] = {}
    panels: list[str] = []
    pos = 0
    n = len(text)
    while pos < n:
        pipe = text.find("|", pos)
        if pipe < 0:
            break
        length_str = text[pos:pipe]
        if not length_str.isdigit():
            break
        length = int(length_str)
        pos = pipe + 1
        pipe = text.find("|", pos)
        if pipe < 0:
            break
        typ = text[pos:pipe]
        pos = pipe + 1
        pipe = text.find("|", pos)
        if pipe < 0:
            break
        field_id = text[pos:pipe]
        pos = pipe + 1
        content = text[pos : pos + length]
        pos += length
        if pos < n and text[pos] == "|":
            pos += 1

        typ_l = typ.lower()
        if typ_l == "hiddenfield":
            updates[field_id] = content
        elif typ_l == "updatepanel":
            panels.append(content)

    for panel in panels:
        updates.update(parse_form_fields(panel))
    return updates


def apply_async_updates(fields: dict[str, str], delta_text: str) -> dict[str, str]:
    """Mescla tokens/campos retornados por postback assíncrono."""
    merged = dict(fields)
    merged.update(parse_async_delta(delta_text))
    return merged


def encode_multipart_form(
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    """Monta body multipart/form-data. files: nome → (filename, content, content_type)."""
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    parts: list[bytes] = []
    dash = f"--{boundary}\r\n".encode("ascii")

    for name, value in fields.items():
        parts.append(dash)
        parts.append(
            (
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )

    for name, (filename, content, content_type) in files.items():
        safe_name = filename.replace('"', "_").replace("\r", " ").replace("\n", " ")
        parts.append(dash)
        parts.append(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{safe_name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        parts.append(content)
        parts.append(b"\r\n")

    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _filename_from_headers(headers: dict[str, str], url: str) -> str:
    """Extrai o nome do arquivo de Content-Disposition ou da URL."""
    disposition = ""
    for key, value in headers.items():
        if key.lower() == "content-disposition":
            disposition = value
            break
    if disposition:
        star = re.search(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", disposition, re.I)
        if star:
            return Path(unquote(star.group(1).strip().strip('"'))).name
        normal = re.search(r'filename\s*=\s*"([^"]+)"', disposition, re.I)
        if not normal:
            normal = re.search(r"filename\s*=\s*([^;]+)", disposition, re.I)
        if normal:
            return Path(unquote(normal.group(1).strip().strip('"'))).name
    return Path(unquote(urlsplit(url).path)).name or "download"


class AspNetSession:
    """Sessão HTTP com cookies, GET/POST form-urlencoded."""

    def __init__(self, base_url: str = BASE_URL, *, timeout: float = 60.0) -> None:
        self.base = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def get(self, path: str) -> tuple[str, bytes, str]:
        url = urljoin(self.base, path.lstrip("/"))
        parts = urlsplit(url)
        url = urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                quote(unquote(parts.path), safe="/"),
                parts.query,
                parts.fragment,
            )
        )
        try:
            with self.opener.open(url, timeout=self.timeout) as resp:
                return resp.geturl(), resp.read(), resp.headers.get("Content-Type", "")
        except HTTPError as exc:
            raise RuntimeError(f"GET {url} falhou: HTTP {exc.code} {exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"GET {url} falhou: {exc.reason}") from exc

    def post(
        self,
        path: str,
        fields: dict[str, str],
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[str, bytes, str]:
        url = urljoin(self.base, path.lstrip("/"))
        body = urlencode(fields).encode("utf-8")
        req_headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if headers:
            req_headers.update(headers)
        req = Request(url, data=body, headers=req_headers, method="POST")
        try:
            with self.opener.open(req, timeout=timeout or self.timeout) as resp:
                return resp.geturl(), resp.read(), resp.headers.get("Content-Type", "")
        except HTTPError as exc:
            raise RuntimeError(f"POST {url} falhou: HTTP {exc.code} {exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"POST {url} falhou: {exc.reason}") from exc

    def post_download(
        self,
        path: str,
        fields: dict[str, str],
        *,
        timeout: float | None = None,
    ) -> tuple[bytes, str, str]:
        """POST que espera um arquivo. Retorna (conteúdo, content_type, filename)."""
        url = urljoin(self.base, path.lstrip("/"))
        body = urlencode(fields).encode("utf-8")
        req = Request(
            url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with self.opener.open(req, timeout=timeout or self.timeout) as resp:
                filename = _filename_from_headers(
                    dict(resp.headers.items()),
                    resp.geturl(),
                )
                return (
                    resp.read(),
                    resp.headers.get("Content-Type", ""),
                    filename,
                )
        except HTTPError as exc:
            raise RuntimeError(f"POST {url} falhou: HTTP {exc.code} {exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"POST {url} falhou: {exc.reason}") from exc

    def post_multipart(
        self,
        path: str,
        fields: dict[str, str],
        files: dict[str, tuple[str, bytes, str]],
        *,
        timeout: float | None = None,
    ) -> tuple[str, bytes, str]:
        """POST multipart/form-data (upload de arquivo no Web Forms)."""
        url = urljoin(self.base, path.lstrip("/"))
        body, content_type = encode_multipart_form(fields, files)
        req = Request(
            url,
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        try:
            with self.opener.open(req, timeout=timeout or self.timeout) as resp:
                return resp.geturl(), resp.read(), resp.headers.get("Content-Type", "")
        except HTTPError as exc:
            raise RuntimeError(f"POST {url} falhou: HTTP {exc.code} {exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"POST {url} falhou: {exc.reason}") from exc

    def post_multipart_html(
        self,
        path: str,
        fields: dict[str, str],
        files: dict[str, tuple[str, bytes, str]],
        *,
        timeout: float | None = None,
    ) -> str:
        _, data, _ = self.post_multipart(path, fields, files, timeout=timeout)
        return data.decode("utf-8", errors="replace")

    def get_html(self, path: str) -> str:
        _, data, _ = self.get(path)
        return data.decode("utf-8", errors="replace")

    def post_html(self, path: str, fields: dict[str, str]) -> str:
        _, data, _ = self.post(path, fields)
        return data.decode("utf-8", errors="replace")

    def post_async(self, path: str, fields: dict[str, str]) -> str:
        """POST de UpdatePanel (ASP.NET AJAX)."""
        payload = dict(fields)
        payload.setdefault("__ASYNCPOST", "true")
        _, data, _ = self.post(
            path,
            payload,
            headers={
                "X-MicrosoftAjax": "Delta=true",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        return data.decode("utf-8", errors="replace")


def _looks_like_login(url: str, html: str) -> bool:
    return "/Login" in url and bool(PASSWORD_FIELD.search(html))


def login(session: AspNetSession | None = None) -> AspNetSession:
    """Faz login e devolve a sessão autenticada."""
    user, password = require_credentials()
    session = session or AspNetSession()

    html = session.get_html("/Login")
    fields = parse_hidden_fields(html)
    fields.update(
        {
            "txtemail": user,
            "txtsenha": password,
            "btnlogin": "Login",
            "txtemailrecuperacao": "",
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
        }
    )
    final_url, data, _ = session.post("/Login", fields)
    body = data.decode("utf-8", errors="replace")

    if _looks_like_login(final_url, body):
        raise RuntimeError(
            "Login no Idebras falhou (ainda na tela de Login). "
            "Verifique LOGIN_USER e LOGIN_PASS no `.env`."
        )

    check_url, check_data, _ = session.get("/Inicio")
    check_html = check_data.decode("utf-8", errors="replace")
    if _looks_like_login(check_url, check_html):
        raise RuntimeError(
            "Login no Idebras falhou (ainda na tela de Login). "
            "Verifique LOGIN_USER e LOGIN_PASS no `.env`."
        )

    return session
