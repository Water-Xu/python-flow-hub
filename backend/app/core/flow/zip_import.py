"""Python 脚本压缩包解析（决策：导入即编排）。

解析 zip：`.py` 文件解析为调用块（Block），其余文本文件作为「资源」随 Flow 存储，
并按目录层级构建文件夹树供前端以「文件夹」形态展示。

安全：防 zip 炸弹（限制单文件与总解压体积）、防路径穿越（忽略绝对路径与 `..`）。
"""

from __future__ import annotations

import ast
import io
import posixpath
import zipfile
from dataclasses import dataclass, field
from typing import Any

# 入口函数第一个参数的约定名（见 pyflow_runtime.executor）
_ENTRYPOINT_INPUT_ARG = "inputs"

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


def _has_valid_entrypoint(code: str) -> bool:
    """判断脚本是否包含合法入口函数（顶层函数第一个参数名为 ``inputs``）。

    用于过滤 pack.py 等工具脚本：这类脚本不暴露 ``def f(inputs): ...`` 入口，
    不应作为可执行块参与编排，导入后在画布上置灰。

    :param code: 脚本源码
    :return: 含至少一个合法入口函数返回 True；语法错误返回 False
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        args = node.args.args
        if args and args[0].arg == _ENTRYPOINT_INPUT_ARG:
            return True
    return False


def _extract_return_keys(code: str) -> set[str]:
    """静态扫描脚本所有 ``return {...}`` 字面量字典的字符串 key。

    仅识别 ``return`` 直接返回的字典字面量（``ast.Dict``），其字符串常量 key
    视为该块对下游暴露的输出端口名。

    :param code: 脚本源码
    :return: 输出 key 集合；语法错误返回空集合
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
            continue
        for key_node in node.value.keys:
            if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                keys.add(key_node.value)
    return keys


def _extract_input_keys(code: str) -> set[str]:
    """静态扫描脚本对输入字典的取值 key，识别两种模式：

    - ``inputs.get("key")`` / ``inputs.get("key", default)``
    - ``inputs["key"]``

    这些 key 视为该块从上游消费的输入端口名。

    :param code: 脚本源码
    :return: 输入 key 集合；语法错误返回空集合
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    keys: set[str] = set()
    for node in ast.walk(tree):
        # inputs.get("key")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == _ENTRYPOINT_INPUT_ARG
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
        # inputs["key"]
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == _ENTRYPOINT_INPUT_ARG
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            keys.add(node.slice.value)
    return keys


def _reachable(adj: dict[str, set[str]], start: str, target: str) -> bool:
    """在有向图 ``adj`` 中判断从 ``start`` 是否可达 ``target``（DFS）。"""
    if start == target:
        return True
    stack = [start]
    seen: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for nxt in adj.get(cur, set()):
            if nxt == target:
                return True
            stack.append(nxt)
    return False


def infer_data_flow_edges(
    scripts: dict[str, str],
    node_id_map: dict[str, str],
) -> list[dict[str, Any]]:
    """推断脚本块之间的数据流边：producer 输出 key ∩ consumer 输入 key ≠ ∅。

    遍历 ``node_id_map`` 中的脚本两两比较（排除自身连自身）：若生产者 ``return``
    暴露的 key 与消费者 ``inputs`` 读取的 key 存在交集，则为候选边。

    为保证导入后的流程可直接执行（拓扑无环，否则 ``topological_order`` 报错无法运行），
    候选边按匹配 key 数量降序贪心加入，跳过任何会形成环的边——即同一对块出现双向
    候选（如 A 返回 ``rows`` 且 A 消费 ``rows``、B 同样）时，仅保留更强的方向。

    :param scripts: {脚本路径: 源码}（来自 :func:`parse_zip`）
    :param node_id_map: {脚本路径: 画布节点 ID}（仅含合法入口脚本）
    :return: [{source_node_id, target_node_id, source_port, target_port, matched_keys}]
    """
    paths = list(node_id_map.keys())
    return_keys: dict[str, set[str]] = {
        p: _extract_return_keys(scripts.get(p, "")) for p in paths
    }
    input_keys: dict[str, set[str]] = {
        p: _extract_input_keys(scripts.get(p, "")) for p in paths
    }

    candidates: list[dict[str, Any]] = []
    for src_path in paths:
        for dst_path in paths:
            if src_path == dst_path:
                continue
            matched = return_keys[src_path] & input_keys[dst_path]
            if matched:
                candidates.append({
                    "src_path": src_path,
                    "dst_path": dst_path,
                    "matched": sorted(matched),
                })

    # 强边优先（匹配 key 多者优先），路径名作稳定次序；贪心加入并跳过成环边
    candidates.sort(key=lambda c: (-len(c["matched"]), c["src_path"], c["dst_path"]))

    adj: dict[str, set[str]] = {node_id_map[p]: set() for p in paths}
    edges: list[dict[str, Any]] = []
    for cand in candidates:
        src_id = node_id_map[cand["src_path"]]
        dst_id = node_id_map[cand["dst_path"]]
        # 加入 src -> dst 前，若 dst 已可达 src，则形成环，跳过
        if _reachable(adj, dst_id, src_id):
            continue
        adj[src_id].add(dst_id)
        edges.append({
            "source_node_id": src_id,
            "target_node_id": dst_id,
            "source_port": "output",
            "target_port": "inputs",
            "matched_keys": cand["matched"],
        })
    return edges


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
