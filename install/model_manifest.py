"""模型资产清单命令行入口。

安装器脚本从 ``install/`` 目录执行时，仍复用应用侧的同一套检查逻辑，
避免安装前后出现两份不一致的模型判断规则。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from infrastructure.model_assets import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
