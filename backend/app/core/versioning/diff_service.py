"""两版本代码 diff（Phase 3，供 Monaco diff 视图）。"""

from __future__ import annotations

import difflib
from typing import Any


def unified_diff(old_text: str, new_text: str, *, old_label: str = "old", new_label: str = "new") -> str:
    """生成统一 diff 文本。"""
    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=old_label,
        tofile=new_label,
        lineterm="",
    )
    return "".join(diff)


def diff_stats(old_text: str, new_text: str) -> dict[str, int]:
    """统计增删行数（用于版本列表概览）。"""
    added = 0
    removed = 0
    for line in difflib.ndiff(old_text.splitlines(), new_text.splitlines()):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    return {"added": added, "removed": removed}


def diff_payload(old_text: str, new_text: str, *, old_label: str = "old", new_label: str = "new") -> dict[str, Any]:
    """前端 Monaco DiffEditor 直接消费：返回原文 + 统计 + unified。"""
    return {
        "old": old_text,
        "new": new_text,
        "old_label": old_label,
        "new_label": new_label,
        "stats": diff_stats(old_text, new_text),
        "unified": unified_diff(old_text, new_text, old_label=old_label, new_label=new_label),
    }
