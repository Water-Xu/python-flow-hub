"""Python 脚本压缩包解析（决策：导入即编排）。

解析 zip：`.py` 文件解析为调用块（Block），其余文本文件作为「资源」随 Flow 存储，
并按目录层级构建文件夹树供前端以「文件夹」形态展示。

安全：防 zip 炸弹（限制单文件与总解压体积）、防路径穿越（忽略绝对路径与 `..`）。
"""

from __future__ import annotations

import io
import posixpath
import zipfile
from dataclasses import dataclass, field
from typing import Any

# 单文件最大解压体积（2MB）
MAX_FILE_BYTES = 2 * 1024 * 1024
# 整包最大解压体积（20MB）
MAX_TOTAL_BYTES = 20 * 1024 * 1024
# 忽略的目录片段
_IGNORE_DIRS = {"__pycache__", ".git", ".idea", ".vscode", "node_modules", ".venv", "venv"}
_BINARY_PLACEHOLDER = "<二进制文件，未解析为文本>"


@dataclass
class ParsedZip:
    """解析结果：py 脚本与资源文件（均保留 zip 内相对路径）。"""

    scripts: dict[str, str] = field(default_factory=dict)
    resources: dict[str, str] = field(default_factory=dict)


def _is_safe_path(name: str) -> bool:
    if not name or name.endswith("/"):
        return False
    norm = posixpath.normpath(name)
    if norm.startswith("/") or norm.startswith("..") or ".." in norm.split("/"):
        return False
    parts = norm.split("/")
    return not any(p in _IGNORE_DIRS for p in parts)


def parse_zip(data: bytes) -> ParsedZip:
    """解析 zip 字节流，返回脚本与资源映射。非法/超限内容静默跳过。"""
    result = ParsedZip()
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir() or not _is_safe_path(info.filename):
                continue
            if info.file_size > MAX_FILE_BYTES:
                continue
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                break
            raw = zf.read(info)
            name = posixpath.normpath(info.filename)
            if name.lower().endswith(".py"):
                result.scripts[name] = _decode(raw)
            else:
                result.resources[name] = _decode(raw)
    return result


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("gbk")
        except UnicodeDecodeError:
            return _BINARY_PLACEHOLDER


def build_tree(leaves: list[dict[str, Any]]) -> dict[str, Any]:
    """由叶子节点（含 path/kind/block_id/node_id）构建嵌套文件夹树。

    leaves: [{"path": "src/a.py", "kind": "block", "block_id": "..", "node_id": ".."}, ...]
    返回 root 文件夹节点。
    """
    root: dict[str, Any] = {"name": "/", "kind": "folder", "path": "", "children": []}

    def _ensure_folder(parts: list[str]) -> dict[str, Any]:
        cur = root
        acc = ""
        for part in parts:
            acc = f"{acc}/{part}" if acc else part
            child = next(
                (c for c in cur["children"] if c["kind"] == "folder" and c["name"] == part),
                None,
            )
            if child is None:
                child = {"name": part, "kind": "folder", "path": acc, "children": []}
                cur["children"].append(child)
            cur = child
        return cur

    for leaf in leaves:
        parts = leaf["path"].split("/")
        folder = _ensure_folder(parts[:-1])
        node = {"name": parts[-1], "kind": leaf["kind"], "path": leaf["path"]}
        if leaf.get("block_id"):
            node["block_id"] = leaf["block_id"]
        if leaf.get("node_id"):
            node["node_id"] = leaf["node_id"]
        folder["children"].append(node)

    _sort_tree(root)
    return root


def _sort_tree(node: dict[str, Any]) -> None:
    children = node.get("children")
    if not children:
        return
    # 文件夹在前，其后块、资源；同类按名称排序
    order = {"folder": 0, "block": 1, "resource": 2}
    children.sort(key=lambda c: (order.get(c["kind"], 3), c["name"].lower()))
    for c in children:
        _sort_tree(c)
