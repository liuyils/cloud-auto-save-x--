from __future__ import annotations

import json
import sys

from app.extensions.adapters.adapter_factory import AdapterFactory


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        json.dump({"ok": False, "message": f"invalid input: {exc}"}, sys.stdout, ensure_ascii=False)
        return 1

    config = payload.get("config")
    cookie = str(payload.get("cookie") or "")
    account_name = str(payload.get("account_name") or "")
    file_path = str(payload.get("path") or "")
    user_agent = str(payload.get("user_agent") or "")

    try:
        adapter = AdapterFactory.create_adapter(
            "cloud189",
            cookie,
            config=config if isinstance(config, dict) else None,
            account_name=account_name,
        )
        if adapter is None:
            raise RuntimeError("创建 cloud189 adapter 失败")
        result = adapter.resolve_download_by_path(file_path, user_agent=user_agent)
        out = {
            "ok": True,
            "url": str(result.get("url") or ""),
            "file_name": str(result.get("file_name") or ""),
            "config": result.get("config") if isinstance(result.get("config"), dict) else {},
        }
        json.dump(out, sys.stdout, ensure_ascii=False)
        return 0
    except Exception as exc:
        json.dump({"ok": False, "message": str(exc)}, sys.stdout, ensure_ascii=False)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
