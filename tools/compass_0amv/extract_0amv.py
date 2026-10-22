#!/usr/bin/env python3
"""Compass Z_SK0AMV daily history extraction entry (unique-implementation launcher).

Extract Compass Z_SK0AMV daily history without modifying Compass files.
`day.vdat` is authoritative for every flushed date; the current `Z_SK0AMV__.cde`
cache can supply the exact completed-day OHLC before Compass flushes that date.

本脚本不包含解析实现。唯一实现是随仓保存的 canonical 解析制品
``compass-0amv-parser``（版本与 SHA256 固定如下，与本仓 Release 同一文件），
入口只运行校验后的 ZIP 内字节，不加载本机同名包。实现唯一化约定见仓库根 README 与制品内 SOURCE.json。

The parsing implementation lives solely in the pinned ``compass-0amv-parser``
artifact (vendored under ``artifact/``, identical to the GitHub Release asset).
"""
from __future__ import annotations

import hashlib
import io
import json
import types
import zipfile
import sys
from pathlib import Path

ARTIFACT_VERSION = "0.1.0"
ARTIFACT_DIR = Path(__file__).resolve().parent / "artifact"
ARTIFACT_ZIP = ARTIFACT_DIR / "compass-0amv-parser-0.1.0.zip"
ARTIFACT_SHA256 = "325efda12ade5cc218909d339ba3afbac8d633ffa0f3680baeeb5daaa560983f"
ARTIFACT_SRC = ARTIFACT_DIR / "compass-0amv-parser-0.1.0" / "src"
ARTIFACT_URL = (
    "https://github.com/Sssovereign/0amv-replication/releases/"
    "download/compass-0amv-parser-0.1.0/compass-0amv-parser-0.1.0.zip"
)


def load_impl():
    """Execute only the bytes read from the pinned artifact, never an ambient package."""
    try:
        payload = ARTIFACT_ZIP.read_bytes()
    except OSError as exc:
        raise SystemExit(f"canonical parser artifact missing: {ARTIFACT_ZIP}") from exc
    if hashlib.sha256(payload).hexdigest() != ARTIFACT_SHA256:
        raise SystemExit("canonical parser artifact checksum mismatch")
    # Keep verification and loading on the same immutable byte buffer (no TOCTOU).
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        prefix = f"compass-0amv-parser-{ARTIFACT_VERSION}/"
        source = json.loads(archive.read(prefix + "SOURCE.json"))
        if source["version"] != ARTIFACT_VERSION:
            raise SystemExit("canonical parser artifact version mismatch")
        member = "src/compass_0amv/extract_0amv.py"
        code = archive.read(prefix + member)
        if hashlib.sha256(code).hexdigest() != source["files"][member]:
            raise SystemExit("canonical parser source checksum mismatch")
    module = types.ModuleType("_verified_compass_0amv")
    module.__file__ = str(ARTIFACT_ZIP) + "/" + member
    exec(compile(code, module.__file__, "exec"), module.__dict__)
    return module


def main(argv=None) -> int:
    impl = load_impl()
    if argv is None:
        return impl.main()
    previous = sys.argv
    try:
        sys.argv = [previous[0], *argv]
        return impl.main()
    finally:
        sys.argv = previous


if __name__ == "__main__":
    raise SystemExit(main())
