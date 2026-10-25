"""Local upstream guard for CR-03 C: records any attempted upstream connection.

Binds 127.0.0.1:8099 and answers 502. Every accepted connection is appended to
upstream-guard-8099-c.log as "CONNECT <utc timestamp> peer=<port> <method> <path>".
Only the request line is read, and the query string is dropped so fake keys never
reach the log.
"""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(__file__).resolve().parent / "upstream-guard-8099-c.log"
RESPONSE = b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"


def main() -> None:
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 8099))
    server.listen(16)
    LOG.write_text("guard listening " + datetime.now(timezone.utc).isoformat() + "\n", encoding="utf-8")
    while True:
        conn, peer = server.accept()
        stamp = datetime.now(timezone.utc).isoformat()
        try:
            head = conn.recv(2048)
            first = head.split(b"\r\n", 1)[0].decode("latin-1")
            parts = first.split(" ")
            method = parts[0] if parts else "-"
            path = parts[1].split("?", 1)[0] if len(parts) > 1 else "-"
        except OSError:
            method, path = "-", "-"
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"CONNECT {stamp} peer={peer[1]} {method} {path}\n")
        try:
            conn.sendall(RESPONSE)
        except OSError:
            pass
        finally:
            conn.close()


if __name__ == "__main__":
    main()
