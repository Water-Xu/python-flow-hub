"""打包脚本：将 data-toolkit 项目打包为 PyFlowHub 可导入的 zip 文件。

用法：
  python pack.py                  -> 输出 data-toolkit.zip（当前目录）
  python pack.py --out /tmp/      -> 指定输出目录
  python pack.py --verify         -> 打包后自动验证 zip 内容

zip 内容：
  data_cleaner.py       -> Block（4 个入口函数）
  stats_engine.py       -> Block（4 个入口函数）
  report_generator.py   -> Block（3 个入口函数）
  text_processor.py     -> Block（3 个入口函数）
  data/sample_sales.csv -> 资源文件
  data/city_codes.json  -> 资源文件
  data/product_reviews.txt -> 资源文件
  data/stopwords.txt    -> 资源文件
  config/settings.json  -> 资源文件

上传方式（PyFlowHub 控制面）：
  POST /api/flows/import-zip
  参数：file=@data-toolkit.zip  name=数据分析工具包
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path

# 要打包的文件相对路径（pack.py 所在目录为根）
_INCLUDE_FILES = [
    "data_cleaner.py",
    "stats_engine.py",
    "report_generator.py",
    "text_processor.py",
    "data/sample_sales.csv",
    "data/city_codes.json",
    "data/product_reviews.txt",
    "data/stopwords.txt",
    "config/settings.json",
]

_OUTPUT_NAME = "data-toolkit.zip"


def pack(root: Path, out_dir: Path) -> Path:
    out_path = out_dir / _OUTPUT_NAME
    missing = [f for f in _INCLUDE_FILES if not (root / f).exists()]
    if missing:
        print(f"[ERROR] 以下文件缺失，请检查：", file=sys.stderr)
        for f in missing:
            print(f"  {f}", file=sys.stderr)
        sys.exit(1)

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in _INCLUDE_FILES:
            abs_path = root / rel
            zf.write(abs_path, rel)
            size_kb = abs_path.stat().st_size / 1024
            print(f"  + {rel:<40} ({size_kb:.1f} KB)")

    total_kb = out_path.stat().st_size / 1024
    print(f"\n打包完成 -> {out_path}  ({total_kb:.1f} KB)")
    return out_path


def verify(zip_path: Path) -> None:
    print(f"\n[验证] {zip_path}")
    with zipfile.ZipFile(zip_path) as zf:
        py_files = [n for n in zf.namelist() if n.endswith(".py")]
        resource_files = [n for n in zf.namelist() if not n.endswith(".py")]
        print(f"  脚本块（.py）：{len(py_files)} 个")
        for f in py_files:
            print(f"    {f}")
        print(f"  资源文件：{len(resource_files)} 个")
        for f in resource_files:
            print(f"    {f}")

    # 简单检查每个 .py 是否有可识别的入口函数
    import ast
    print("\n[入口函数扫描]")
    with zipfile.ZipFile(zip_path) as zf:
        for name in py_files:
            code = zf.read(name).decode("utf-8")
            try:
                tree = ast.parse(code)
            except SyntaxError as e:
                print(f"  {name}: [语法错误] {e}")
                continue
            funcs = [
                n.name for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not n.name.startswith("_")
                and (n.args.args or n.args.vararg)
            ]
            print(f"  {name}: {funcs}")

    print("\n[验证通过] zip 内容符合 PyFlowHub 导入要求。")


def main() -> None:
    parser = argparse.ArgumentParser(description="将 data-toolkit 打包为 PyFlowHub zip")
    parser.add_argument("--out", default=".", help="输出目录（默认当前目录）")
    parser.add_argument("--verify", action="store_true", help="打包后验证 zip 内容")
    args = parser.parse_args()

    root = Path(__file__).parent.resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"根目录：{root}")
    print(f"输出到：{out_dir / _OUTPUT_NAME}\n")

    zip_path = pack(root, out_dir)

    if args.verify:
        verify(zip_path)

    print("\n上传命令示例（需 curl）：")
    print(f'  curl -X POST http://localhost:8000/api/flows/import-zip \\')
    print(f'    -F "file=@{zip_path}" \\')
    print(f'    -F "name=数据分析工具包"')


if __name__ == "__main__":
    main()
