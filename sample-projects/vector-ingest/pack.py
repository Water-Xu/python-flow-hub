"""打包 vector-ingest（pyflowhub_pack 方案：wheel + 薄 wrapper 块）。

部署顺序：
  1. python build_wheel.py
  2. python upload_artifacts.py          # MinIO + GCS
  3. python pack.py --verify
  4. POST /api/flows/import-zip          # name=向量入库
  5. 各块「版本」确认 pip 依赖 → 发布 → 部署中心部署

zip 仅含薄 wrapper .py（<20MB）；逻辑在 wheel；大模型放 MinIO（PYFLOW_VECTOR_MODEL_PREFIX）。
"""

from __future__ import annotations

import argparse
import ast
import sys
import zipfile
from pathlib import Path

_INCLUDE = [
    "blocks/text_embedder.py",
    "blocks/vector_embedder.py",
    "blocks/image_embedder.py",
    "blocks/milvus_writer.py",
    "blocks/text_embedder/requirements.txt",
    "blocks/vector_embedder/requirements.txt",
    "blocks/image_embedder/requirements.txt",
    "blocks/milvus_writer/requirements.txt",
    "data/sample_payload.json",
    "data/sample_payload_image.json",
]

_OUTPUT = "vector-ingest.zip"


def pack(root: Path, out_dir: Path) -> Path:
    out = out_dir / _OUTPUT
    missing = [f for f in _INCLUDE if not (root / f).exists()]
    if missing:
        print("[ERROR] 缺失:", *missing, sep="\n  ", file=sys.stderr)
        sys.exit(1)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in _INCLUDE:
            zf.write(root / rel, rel)
            print(f"  + {rel}")
    print(f"\n-> {out} ({out.stat().st_size / 1024:.1f} KB)")
    return out


def verify(zpath: Path) -> None:
    with zipfile.ZipFile(zpath) as zf:
        py = [n for n in zf.namelist() if n.endswith(".py")]
        for name in py:
            tree = ast.parse(zf.read(name).decode())
            funcs = [
                n.name for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.args.args and n.args.args[0].arg == "inputs"
            ]
            print(f"  {name}: {funcs}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=".")
    p.add_argument("--verify", action="store_true")
    a = p.parse_args()
    root = Path(__file__).parent
    out = pack(root, Path(a.out).resolve())
    if a.verify:
        verify(out)


if __name__ == "__main__":
    main()
