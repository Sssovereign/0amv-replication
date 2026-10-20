"""路径与常量配置；全部可用环境变量覆盖。

- TDX_ROOT:   通达信安装目录（含 vipdoc/ 与 T0002/hq_cache/gbbq）
- COMPASS_ROOT: 指南针客户端目录（仅官方真值提取需要）
- AMV_WORK:   工作产物目录（默认仓库内 work/，已 gitignore）
"""
from pathlib import Path
import os

REPO_ROOT = Path(__file__).resolve().parents[1]

TDX_ROOT = Path(os.environ.get("TDX_ROOT", "F:/tdx"))
COMPASS_ROOT = Path(os.environ.get("COMPASS_ROOT", "F:/Compass"))
WORK = Path(os.environ.get("AMV_WORK", str(REPO_ROOT / "work")))
GBBQ = Path(os.environ.get("AMV_GBBQ", str(TDX_ROOT / "T0002/hq_cache/gbbq")))

__version__ = "0.3beta"
