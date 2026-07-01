from __future__ import annotations

import logging
import os
from typing import Tuple

import grpc

from app.thirdparty.dl302_rpc import dl302_pb2, dl302_pb2_grpc


logger = logging.getLogger(__name__)


def _grpc_addr() -> str:
    addr = str(os.getenv("DL302_GRPC_ADDR", "") or "").strip()
    if not addr:
        return "127.0.0.1:9001"
    return addr


def reload_dl302(*, timeout_seconds: float = 2.0) -> Tuple[bool, str]:
    addr = _grpc_addr()
    try:
        with grpc.insecure_channel(addr) as channel:
            stub = dl302_pb2_grpc.Dl302ServiceStub(channel)
            resp = stub.Reload(dl302_pb2.ReloadRequest(), timeout=timeout_seconds)
            ok = bool(getattr(resp, "ok", False))
            msg = str(getattr(resp, "message", "") or "")
            return ok, msg or ("ok" if ok else "reload failed")
    except Exception as e:
        logger.warning("dl302 reload failed: %s", e)
        return False, str(e)

