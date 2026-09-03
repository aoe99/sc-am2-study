#!/usr/bin/env python3
"""Local static server for the app (§5-2 の「ローカルだけで完結させる手順」).

    python3 tools/serve.py [port]      # 既定 8765 → http://localhost:8765/
"""
from __future__ import annotations
import functools, http.server, socketserver, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "app"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".webmanifest": "application/manifest+json",
        ".json": "application/json",
    }

    def end_headers(self):
        # The app is a single-user local tool; never let a stale module linger.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", PORT),
                            functools.partial(Handler, directory=str(ROOT))) as httpd:
    print(f"serving {ROOT} at http://localhost:{PORT}/", flush=True)
    httpd.serve_forever()
