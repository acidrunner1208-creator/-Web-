"""ローカル確認用の簡易 HTTP サーバー (Basic 認証つき)。

本番の認証は Cloudflare Pages Functions (functions/_middleware.js) が担当します。
これはあくまで手元で public/ を認証付きで確認するためのものです。

    python scripts/preview_server.py --user admin --password demo --port 8000
"""
from __future__ import annotations

import argparse
import base64
import functools
import http.server
import os


class AuthHandler(http.server.SimpleHTTPRequestHandler):
    credentials = ""

    def do_GET(self):  # noqa: N802
        header = self.headers.get("Authorization", "")
        if header != f"Basic {self.credentials}":
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="keiba-simulator"')
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("認証が必要です".encode())
            return
        super().do_GET()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="demo")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--dir", default="public")
    args = ap.parse_args()

    AuthHandler.credentials = base64.b64encode(f"{args.user}:{args.password}".encode()).decode()
    handler = functools.partial(AuthHandler, directory=os.path.abspath(args.dir))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"http://127.0.0.1:{args.port}/  (user={args.user} / password={args.password})")
    print("Ctrl+C で停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
