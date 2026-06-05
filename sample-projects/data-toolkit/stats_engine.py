"""统计分析引擎。

依赖资源文件：data/city_codes.json（城市代码映射，通过 inputs 传入）

入口函数：
  run         — 对数值列计算均值/中位数/标准差/min/max/sum
  top_n       — 按指定列降序取前 N 条
  group_by    — 按指定列分组聚合（sum/count/mean）
  correlation — 计算两列的 Pearson 相关系数
"""

from __future__ import annotations

import math
from collections import defaultdict


def _to_float(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _get_rows(inputs: dict) -> list[dict]:
    rows = inputs.get("rows") or inputs.get("data") or []
    if isinstance(rows, str):
        import csv, io
        reader = csv.DictReader(io.StringIO(rows.strip()))
        rows = list(reader)
    return rows


def run(inputs: dict) -> dict:
    """对数值列计算基础统计指标（count/mean/median/std/min/max/sum）。

    inputs:
      rows (list): 数据行列表（来自 data_cleaner.run 的输出）
      columns (list, 可选): 要统计的列名；不填则自动检测数值列

    returns:
      stats (dict): {列名: {count, mean, median, std, min, max, sum}}
      row_count (int): 总行数
      analyzed_cols (list): 实际分析的列名
    """
    rows = _get_rows(inputs)
    if not rows:
        return {"stats": {}, "row_count": 0, "analyzed_cols": []}

    target_cols: list[str] = inputs.get("columns") or [
        k for k, v in rows[0].items() if _to_float(v) is not None
    ]

    stats: dict = {}
    for col in target_cols:
        values = [_to_float(r.get(col)) for r in rows]
        values = [v for v in values if v is not None]
        if not values:
            continue
        n = len(values)
        mean = sum(values) / n
        sorted_v = sorted(values)
        median = (sorted_v[n // 2] if n % 2
                  else (sorted_v[n // 2 - 1] + sorted_v[n // 2]) / 2)
        variance = sum((x - mean) ** 2 for x in values) / n
        stats[col] = {
            "count": n,
            "mean": round(mean, 4),
            "median": round(median, 4),
            "std": round(math.sqrt(variance), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "sum": round(sum(values), 4),
        }

    return {"stats": stats, "row_count": len(rows), "analyzed_cols": list(stats.keys())}


def top_n(inputs: dict) -> dict:
    """按指定列排序取前 N 条记录。

    inputs:
      rows (list): 数据行列表
      sort_by (str, 可选): 排序列名，默认 "total"
      n (int, 可选): 取前 N 条，默认 5
      ascending (bool, 可选): 升序排列，默认 False（降序）

    returns:
      rows (list): 前 N 条数据
      sort_by (str): 实际排序列
      total_rows (int): 原始总行数
    """
    rows = _get_rows(inputs)
    sort_by: str = inputs.get("sort_by", "total")
    n = int(inputs.get("n", 5))
    ascending: bool = bool(inputs.get("ascending", False))

    def sort_key(r: dict):
        v = _to_float(r.get(sort_by, 0))
        return v if v is not None else 0

    sorted_rows = sorted(rows, key=sort_key, reverse=not ascending)
    return {
        "rows": sorted_rows[:n],
        "sort_by": sort_by,
        "total_rows": len(rows),
        "returned": min(n, len(rows)),
    }


def group_by(inputs: dict) -> dict:
    """按指定列分组聚合。

    inputs:
      rows (list): 数据行列表
      group_col (str, 可选): 分组列名，默认 "city"
      agg_col (str, 可选): 聚合列名，默认 "total"
      agg_func (str, 可选): 聚合函数 sum|count|mean|max|min，默认 "sum"
      city_codes (dict, 可选): 城市代码映射（来自 data/city_codes.json 资源），
                               设置后为分组键附加城市代码

    returns:
      groups (dict): {分组值: 聚合结果}
      group_col (str): 分组列
      agg_col (str): 聚合列
      agg_func (str): 聚合函数
    """
    rows = _get_rows(inputs)
    group_col: str = inputs.get("group_col", "city")
    agg_col: str = inputs.get("agg_col", "total")
    agg_func: str = inputs.get("agg_func", "sum")
    city_codes: dict = inputs.get("city_codes", {})

    buckets: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        key = str(row.get(group_col, "未知"))
        if city_codes and key in city_codes:
            key = f"{key}({city_codes[key]})"
        val = _to_float(row.get(agg_col))
        if val is not None:
            buckets[key].append(val)

    result: dict[str, float | int] = {}
    for key, vals in buckets.items():
        if not vals:
            result[key] = 0
            continue
        if agg_func == "sum":
            result[key] = round(sum(vals), 4)
        elif agg_func == "count":
            result[key] = len(vals)
        elif agg_func == "mean":
            result[key] = round(sum(vals) / len(vals), 4)
        elif agg_func == "max":
            result[key] = round(max(vals), 4)
        elif agg_func == "min":
            result[key] = round(min(vals), 4)
        else:
            result[key] = round(sum(vals), 4)

    sorted_result = dict(
        sorted(result.items(), key=lambda x: -x[1] if isinstance(x[1], (int, float)) else 0)
    )
    return {
        "groups": sorted_result,
        "group_col": group_col,
        "agg_col": agg_col,
        "agg_func": agg_func,
        "group_count": len(sorted_result),
    }


def correlation(inputs: dict) -> dict:
    """计算两列之间的 Pearson 相关系数。

    inputs:
      rows (list): 数据行列表
      col_x (str, 可选): X 列名，默认 "quantity"
      col_y (str, 可选): Y 列名，默认 "total"

    returns:
      correlation (float | None): Pearson 相关系数（-1.0 ~ 1.0）
      col_x, col_y (str): 实际分析的列名
      n (int): 有效数据对数
      interpretation (str): 相关性强度描述
    """
    rows = _get_rows(inputs)
    col_x: str = inputs.get("col_x", "quantity")
    col_y: str = inputs.get("col_y", "total")

    pairs: list[tuple[float, float]] = []
    for r in rows:
        x = _to_float(r.get(col_x))
        y = _to_float(r.get(col_y))
        if x is not None and y is not None:
            pairs.append((x, y))

    if len(pairs) < 2:
        return {"correlation": None, "col_x": col_x, "col_y": col_y, "n": len(pairs),
                "interpretation": "数据不足（需至少 2 对有效值）"}

    n = len(pairs)
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mx, my = sum(xs) / n, sum(ys) / n

    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs) / n)
    sy = math.sqrt(sum((y - my) ** 2 for y in ys) / n)

    if sx == 0 or sy == 0:
        return {"correlation": 0.0, "col_x": col_x, "col_y": col_y, "n": n,
                "interpretation": "其中一列为常量，无法计算相关性"}

    r = round(cov / (sx * sy), 4)
    abs_r = abs(r)
    direction = "正" if r >= 0 else "负"
    if abs_r >= 0.8:
        strength = f"强{direction}相关"
    elif abs_r >= 0.5:
        strength = f"中度{direction}相关"
    elif abs_r >= 0.2:
        strength = f"弱{direction}相关"
    else:
        strength = "几乎无相关性"

    return {
        "correlation": r,
        "col_x": col_x,
        "col_y": col_y,
        "n": n,
        "interpretation": strength,
    }
