"""Web verification flow: numeric image CAPTCHA + Cloudflare Turnstile.

The server is intentionally small and dependency-free. It runs beside the
Telegram polling loop and hands successful challenges back to that loop.
"""

from __future__ import annotations

import hashlib
import html
import hmac
import io
import json
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Awaitable, Callable, Optional

from PIL import Image, ImageDraw, ImageFont


TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
SESSION_TTL = 300
MAX_ATTEMPTS = 5


def is_configured() -> bool:
    return all(
        os.getenv(name)
        for name in (
            "WEB_VERIFY_BASE_URL",
            "CF_TURNSTILE_SITE_KEY",
            "CF_TURNSTILE_SECRET_KEY",
        )
    )


def _font(size: int):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default()


def _captcha_image(answer: str) -> bytes:
    image = Image.new("RGB", (240, 88), (248, 250, 252))
    draw = ImageDraw.Draw(image)
    for _ in range(8):
        draw.line(
            (secrets.randbelow(240), secrets.randbelow(88),
             secrets.randbelow(240), secrets.randbelow(88)),
            fill=(170, 185, 205), width=1,
        )
    for _ in range(180):
        draw.point(
            (secrets.randbelow(240), secrets.randbelow(88)),
            fill=(150, 165, 185),
        )
    draw.text((38, 22), " ".join(answer), font=_font(36), fill=(20, 35, 55))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class WebVerificationServer:
    def __init__(
        self,
        loop,
        on_success: Callable[[str, int], Awaitable[None]],
        host: str = "0.0.0.0",
        port: Optional[int] = None,
    ):
        self.loop = loop
        self.on_success = on_success
        self.host = host
        self.port = port or int(os.getenv("WEB_VERIFY_PORT", "8080"))
        self.base_url = os.getenv("WEB_VERIFY_BASE_URL", "").rstrip("/")
        self.site_key = os.getenv("CF_TURNSTILE_SITE_KEY", "")
        self.secret_key = os.getenv("CF_TURNSTILE_SECRET_KEY", "")
        self.sessions = {}
        self.lock = threading.Lock()
        self.httpd = None
        self.thread = None

    def create_session(self, user_id: int, chat_id: int) -> str:
        token = secrets.token_urlsafe(32)
        answer = "".join(str(secrets.randbelow(10)) for _ in range(6))
        with self.lock:
            self.sessions[token] = {
                "user_id": user_id,
                "chat_id": chat_id,
                "answer": _hash(answer),
                "captcha": answer,
                "created_at": time.time(),
                "attempts": 0,
                "used": False,
            }
        return token

    def start(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def _send(self, status, content_type, body):
                if isinstance(body, str):
                    body = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _session(self, token):
                with server.lock:
                    session = server.sessions.get(token)
                    if not session or session["used"] or time.time() - session["created_at"] > SESSION_TTL:
                        return None
                    return dict(session)

            def do_GET(self):
                path = urllib.parse.urlparse(self.path).path
                if path == "/healthz":
                    self._send(HTTPStatus.OK, "text/plain; charset=utf-8", "ok")
                    return
                prefix = "/verify/"
                if path.startswith(prefix):
                    token = path[len(prefix):]
                    session = self._session(token)
                    if not session:
                        self._send(HTTPStatus.GONE, "text/html; charset=utf-8", "驗證連結已失效。")
                        return
                    body = _page(token, server.site_key, session["captcha"])
                    self._send(HTTPStatus.OK, "text/html; charset=utf-8", body)
                    return
                self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", "Not found")

            def do_POST(self):
                path = urllib.parse.urlparse(self.path).path
                prefix = "/verify/"
                if not path.startswith(prefix):
                    self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", "Not found")
                    return
                token = path[len(prefix):]
                session = self._session(token)
                if not session:
                    self._send(HTTPStatus.GONE, "text/html; charset=utf-8", "驗證連結已失效。")
                    return
                length = min(int(self.headers.get("Content-Length", "0")), 10000)
                raw = self.rfile.read(length)
                form = urllib.parse.parse_qs(raw.decode("utf-8", "replace"))
                answer = form.get("captcha", [""])[0].strip()
                turnstile = form.get("cf-turnstile-response", [""])[0]
                with server.lock:
                    current = server.sessions.get(token)
                    current["attempts"] += 1
                    attempts = current["attempts"]
                if attempts > MAX_ATTEMPTS or not hmac.compare_digest(_hash(answer), session["answer"]):
                    self._send(HTTPStatus.BAD_REQUEST, "text/html; charset=utf-8", _page(token, server.site_key, session["captcha"], "數字驗證碼錯誤，請重新輸入。"))
                    return
                if not _verify_turnstile(server.secret_key, turnstile, self.client_address[0]):
                    self._send(HTTPStatus.BAD_REQUEST, "text/html; charset=utf-8", _page(token, server.site_key, session["captcha"], "Cloudflare 驗證未通過，請重試。"))
                    return
                with server.lock:
                    current = server.sessions.get(token)
                    if not current or current["used"]:
                        self._send(HTTPStatus.GONE, "text/html; charset=utf-8", "驗證已完成或失效。")
                        return
                    current["used"] = True
                future = __import__("asyncio").run_coroutine_threadsafe(
                    server.on_success(token, session["user_id"]), server.loop
                )
                try:
                    future.result(timeout=15)
                except Exception:
                    self._send(HTTPStatus.INTERNAL_SERVER_ERROR, "text/html; charset=utf-8", "驗證完成，但 Bot 尚未完成解除限制，請聯絡管理員。")
                    return
                self._send(HTTPStatus.OK, "text/html; charset=utf-8", "<h2>驗證成功</h2><p>你可以回到 Telegram 群組了。</p>")

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="web-verification", daemon=True)
        self.thread.start()

    def url(self, token: str) -> str:
        return f"{self.base_url}/verify/{urllib.parse.quote(token, safe='')}"

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()


def _verify_turnstile(secret: str, token: str, remote_ip: str) -> bool:
    if not secret or not token:
        return False
    payload = json.dumps({"secret": secret, "response": token, "remoteip": remote_ip}).encode("utf-8")
    request = urllib.request.Request(
        TURNSTILE_VERIFY_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            result = json.loads(response.read().decode("utf-8"))
        return bool(result.get("success"))
    except Exception:
        return False


def _page(token: str, site_key: str, captcha: str, error: str = "") -> str:
    safe_token = html.escape(token, quote=True)
    safe_key = html.escape(site_key, quote=True)
    safe_captcha = html.escape(captcha)
    safe_error = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Telegram 入群驗證</title><script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script><style>body{{font-family:system-ui,sans-serif;background:#101827;color:#eef4ff;display:grid;place-items:center;min-height:100vh;margin:0}}main{{width:min(420px,calc(100% - 32px));background:#17243a;padding:28px;border-radius:16px;box-shadow:0 12px 40px #0005}}h1{{font-size:22px}}img{{display:block;width:240px;height:88px;margin:20px auto;border-radius:8px}}input{{width:100%;box-sizing:border-box;padding:12px;border:1px solid #58708f;border-radius:8px;background:#0e1726;color:white;font-size:18px;letter-spacing:6px;text-align:center}}button{{width:100%;margin-top:16px;padding:12px;border:0;border-radius:8px;background:#4fa3ff;color:#07111f;font-weight:700;font-size:16px}}.error{{color:#ff9a9a}}.cf{{margin-top:16px}}</style></head><body><main><h1>Telegram 入群驗證</h1><p>請輸入圖片中的 6 位數字，並完成 Cloudflare 驗證。</p>{safe_error}<img src="data:image/png;base64,{__import__('base64').b64encode(_captcha_image(captcha)).decode()}" alt="數字驗證碼"><form method="post"><input name="captcha" inputmode="numeric" pattern="[0-9]{{6}}" maxlength="6" autocomplete="off" required><div class="cf"><div class="cf-turnstile" data-sitekey="{safe_key}"></div></div><button type="submit">完成驗證</button></form></main></body></html>"""
