# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Loopback-only research server. Only public UI files can be served."""
from __future__ import annotations

import json
import mimetypes
import secrets
import threading
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import ROOT
from .service import WattDialogueService

STATIC_FILES = {"/": "index.html", "/index.html": "index.html", "/style.css": "style.css",
                "/app.js": "app.js", "/favicon.svg": "favicon.svg"}


class DisplayServer(ThreadingHTTPServer):
    def __init__(self, address, service):
        if address[0] not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("The proof-of-concept server must bind to loopback.")
        super().__init__(address, DisplayHandler)
        self.service = service
        self.sessions = {}
        self.session_lock = threading.RLock()


class DisplayHandler(BaseHTTPRequestHandler):
    server_version = "WattDialoguePrototype/0.1"

    def log_message(self, format, *args):
        # Do not log question text, query parameters, cookies or credentials.
        pass

    def _host_ok(self):
        host = self.headers.get("Host", "").split(":", 1)[0]
        return host in {"127.0.0.1", "localhost"}

    def _session(self):
        jar = cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except cookies.CookieError:
            pass
        token = jar.get("wd_session")
        token = token.value if token else None
        with self.server.session_lock:
            if token not in self.server.sessions:
                token = secrets.token_urlsafe(32)
                self.server.sessions[token] = {"home_scope": "R1Hz", "csrf_token": secrets.token_urlsafe(32)}
            self.session_id = token
            return self.server.sessions[token]

    def _headers(self, status, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        if getattr(self, "session_id", None):
            self.send_header("Set-Cookie", f"wd_session={self.session_id}; HttpOnly; SameSite=Strict; Path=/")
        self.end_headers()

    def _json(self, status, payload):
        body = json.dumps(payload, allow_nan=False).encode()
        self._headers(status, "application/json; charset=utf-8")
        self.wfile.write(body)

    def _home(self, query, session):
        requested = query.get("home", [session["home_scope"]])[0]
        if requested != session["home_scope"]:
            raise PermissionError("The request is outside the selected household session.")
        return requested

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"error": "This prototype accepts only loopback requests."})
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        session = self._session()
        try:
            if parsed.path in STATIC_FILES:
                file = ROOT / "web" / STATIC_FILES[parsed.path]
                if not file.is_file():
                    return self._json(404, {"error": "Not found."})
                self._headers(200, (mimetypes.guess_type(file.name)[0] or "application/octet-stream") + "; charset=utf-8")
                return self.wfile.write(file.read_bytes())
            if parsed.path == "/api/status":
                return self._json(200, {**self.server.service.status(), **session})
            if parsed.path == "/api/blocks":
                return self._json(200, self.server.service.blocks(self._home(query, session)))
            if parsed.path == "/api/summary":
                home = self._home(query, session)
                block = int(query.get("block_id", [self.server.service.store.list_blocks()[home][0]])[0])
                return self._json(200, self.server.service.summary(home, block, query.get("as_of", [None])[0]))
            return self._json(404, {"error": "Not found."})
        except PermissionError as exc:
            return self._json(403, {"error": str(exc)})
        except (ValueError, KeyError, TypeError) as exc:
            return self._json(400, {"error": str(exc)[:250]})

    def do_POST(self):
        if not self._host_ok():
            return self._json(403, {"error": "This prototype accepts only loopback requests."})
        session = self._session()
        if not secrets.compare_digest(self.headers.get("X-WattDialogue-Token", ""), session["csrf_token"]):
            return self._json(403, {"error": "The display session token is missing or invalid."})
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            return self._json(403, {"error": "Requests must originate from this display."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 20000:
                raise ValueError("Request size is invalid.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("A JSON object is required.")
            path = urlparse(self.path).path
            if path == "/api/home":
                home = payload.get("home")
                if home not in self.server.service.store.list_blocks():
                    raise ValueError("Choose an available archive recording.")
                with self.server.session_lock:
                    session["home_scope"] = home
                return self._json(200, {"ok": True, "home_scope": home})
            if payload.get("home", session["home_scope"]) != session["home_scope"]:
                raise PermissionError("The request is outside the selected household session.")
            if path == "/api/query":
                return self._json(200, self.server.service.query(payload, session["home_scope"]))
            if path == "/api/labels":
                return self._json(200, self.server.service.confirm_label(payload, session["home_scope"]))
            return self._json(404, {"error": "Not found."})
        except PermissionError as exc:
            return self._json(403, {"error": str(exc)})
        except (ValueError, KeyError, TypeError) as exc:
            return self._json(400, {"error": str(exc)[:250]})


def serve(port=8767, source_root=None, env_file=None):
    service = WattDialogueService(source_root=source_root, env_file=env_file)
    server = DisplayServer(("127.0.0.1", int(port)), service)
    print(f"WattDialogue in-home display prototype: http://127.0.0.1:{server.server_port}", flush=True)
    print("Historical replay. Local mode is the default. Server-only credentials; bounded cloud calls.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
