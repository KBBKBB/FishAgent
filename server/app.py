#!/usr/bin/env python3
"""M2 服务入口。

用法:
    python3 app.py --offline --port 8000      # 无需任何 Key（mock + 合成气象）
    export AMAP_KEY=xxx && python3 app.py     # 真实链路
"""

from __future__ import annotations

import argparse

from fishagent import services
from fishagent.api import make_server


def main() -> int:
    ap = argparse.ArgumentParser(description="FishAgent M2 MVP 服务")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--offline", action="store_true", help="mock 高德 + 合成气象（无需 Key）")
    args = ap.parse_args()

    ctx = services.build_context(offline=args.offline)
    httpd = make_server(args.host, args.port, ctx)
    print(f"FishAgent M2 listening on http://{args.host}:{args.port}  (offline={args.offline})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
