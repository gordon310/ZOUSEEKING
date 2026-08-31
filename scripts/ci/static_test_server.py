from __future__ import annotations

import argparse
import json
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit


def load_content_library(path: Path) -> bytes:
    """Read and validate the tracked canonical library without writing a copy."""

    payload = path.read_bytes()
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, list):
        raise ValueError("content library must be a JSON array")
    return payload


class FixtureRequestHandler(SimpleHTTPRequestHandler):
    content_library_path: Path

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if urlsplit(self.path).path == "/content-library.json":
            try:
                payload = load_content_library(self.content_library_path)
            except (OSError, ValueError):
                self.send_error(500, "content library fixture unavailable")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve web fixtures with the canonical content library.")
    parser.add_argument("--web-root", type=Path, required=True)
    parser.add_argument("--content-library", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    FixtureRequestHandler.content_library_path = args.content_library.resolve()
    handler = partial(FixtureRequestHandler, directory=str(args.web_root.resolve()))
    server = HTTPServer((args.host, args.port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
