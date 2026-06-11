"""构建 pyflow-vector-ingest wheel（pyflowhub_pack 方案第 1 步）。"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = ROOT / "pyflow_vector"
DIST = ROOT / "dist"


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "build"],
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(DIST)],
        cwd=PKG,
        check=True,
    )
    wheels = list(DIST.glob("*.whl"))
    if not wheels:
        raise SystemExit("未生成 wheel")
    print(f"wheel -> {wheels[0]}")


if __name__ == "__main__":
    main()
