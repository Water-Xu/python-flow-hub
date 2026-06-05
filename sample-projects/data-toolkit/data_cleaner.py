"""数据清洗工具块。

依赖资源文件：data/sample_sales.csv（内置示例，可通过 inputs.csv_data 覆盖）

入口函数：
  run             — 默认入口：解析 CSV + 去重 + 数值列类型转换
  remove_duplicates — 按指定列去重
  normalize_columns — 列名标准化（小写 + 去空格）
  fill_missing    — 填充缺失值
"""

from __future__ import annotations

import csv
import io

# 内置示例数据（当 inputs 未提供 csv_data 时使用）
_SAMPLE_CSV = """date,city,product,quantity,price,total
2024-01-01,北京,产品A,10,99.9,999.0
2024-01-01,上海,产品B,5,199.0,995.0
2024-01-02,北京,产品A,8,99.9,799.2
2024-01-02,广州,产品C,12,49.5,594.0
2024-01-03,上海,产品B,3,199.0,597.0
2024-01-03,北京,产品A,10,99.9,999.0
2024-01-04,广州,产品C,7,49.5,346.5
2024-01-04,深圳,产品D,15,299.0,4485.0
2024-01-05,北京,产品B,6,199.0,1194.0
2024-01-05,上海,产品A,9,99.9,899.1
2024-01-06,成都,产品D,4,299.0,1196.0
2024-01-06,广州,产品A,11,99.9,1098.9
2024-01-07,深圳,产品B,8,199.0,1592.0
2024-01-07,北京,产品C,6,49.5,297.0
2024-01-08,上海,产品D,3,299.0,897.0
2024-01-08,成都,产品A,7,99.9,699.3
2024-01-09,广州,产品B,9,199.0,1791.0
2024-01-09,深圳,产品C,14,49.5,693.0
2024-01-10,北京,产品D,2,299.0,598.0
2024-01-10,上海,产品C,8,49.5,396.0"""

_NUMERIC_COLS = {"quantity", "price", "total"}


def _parse_csv(csv_text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    return list(reader)


def _get_rows(inputs: dict) -> list[dict]:
    """从 inputs 获取数据行；支持 csv_data 文本或已解析的 rows 列表。"""
    if "rows" in inputs and isinstance(inputs["rows"], list):
        return inputs["rows"]
    csv_text = inputs.get("csv_data") or inputs.get("data") or _SAMPLE_CSV
    if isinstance(csv_text, list):
        return csv_text
    return _parse_csv(str(csv_text))


def _to_float(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def run(inputs: dict) -> dict:
    """解析 CSV 并返回清洗后的数据（去重 + 数值列类型转换）。

    inputs:
      csv_data (str, 可选): CSV 格式文本；不填则使用内置示例数据
      numeric_cols (list, 可选): 需要转换为浮点数的列，默认 ["quantity","price","total"]

    returns:
      rows (list): 清洗后的数据行列表
      count (int): 数据行数
      columns (list): 列名列表
      numeric_cols (list): 已转换的数值列
    """
    raw_rows = _get_rows(inputs)
    numeric_cols = set(inputs.get("numeric_cols", list(_NUMERIC_COLS)))

    cleaned: list[dict] = []
    seen: set = set()
    for row in raw_rows:
        key = tuple(sorted(row.items()))
        if key in seen:
            continue
        seen.add(key)
        r = dict(row)
        for col in numeric_cols:
            if col in r:
                converted = _to_float(r[col])
                r[col] = converted if converted is not None else r[col]
        cleaned.append(r)

    return {
        "rows": cleaned,
        "count": len(cleaned),
        "columns": list(cleaned[0].keys()) if cleaned else [],
        "numeric_cols": list(numeric_cols),
    }


def remove_duplicates(inputs: dict) -> dict:
    """按指定列去除重复行。

    inputs:
      csv_data / rows: 数据源
      key_cols (list, 可选): 判断重复的列名，默认使用全部列

    returns:
      rows (list): 去重后的行
      original_count (int): 原始行数
      removed_count (int): 删除的重复行数
    """
    rows = _get_rows(inputs)
    key_cols: list[str] | None = inputs.get("key_cols")
    original_count = len(rows)

    seen: set = set()
    unique: list[dict] = []
    for row in rows:
        cols = key_cols if key_cols else list(row.keys())
        key = tuple(row.get(c, "") for c in cols)
        if key not in seen:
            seen.add(key)
            unique.append(row)

    return {
        "rows": unique,
        "original_count": original_count,
        "removed_count": original_count - len(unique),
    }


def normalize_columns(inputs: dict) -> dict:
    """列名标准化：去首尾空格 + 转小写 + 空格替换为下划线。

    inputs:
      csv_data / rows: 数据源
      rename_map (dict, 可选): 自定义覆盖映射 {"旧名": "新名"}

    returns:
      rows (list): 列名标准化后的数据行
      column_mapping (dict): 实际应用的列名映射
    """
    rows = _get_rows(inputs)
    rename_map: dict[str, str] = inputs.get("rename_map", {})

    if not rows:
        return {"rows": [], "column_mapping": {}}

    mapping: dict[str, str] = {}
    for col in rows[0].keys():
        auto = col.strip().lower().replace(" ", "_")
        mapping[col] = rename_map.get(col, auto)

    normalized_rows = [{mapping[k]: v for k, v in row.items()} for row in rows]
    return {"rows": normalized_rows, "column_mapping": mapping}


def fill_missing(inputs: dict) -> dict:
    """填充缺失值（None 或空字符串）。

    inputs:
      csv_data / rows: 数据源
      fill_values (dict, 可选): 各列填充值，如 {"city": "未知", "quantity": 0}
        默认：数值列填 0，文本列填 "N/A"

    returns:
      rows (list): 填充后的数据行
      filled_cells (int): 实际填充的单元格数
    """
    rows = _get_rows(inputs)
    fill_values: dict = inputs.get("fill_values", {})
    filled_cells = 0

    result: list[dict] = []
    for row in rows:
        r: dict = {}
        for k, v in row.items():
            if v is None or v == "":
                default = fill_values.get(k, 0 if k in _NUMERIC_COLS else "N/A")
                r[k] = default
                filled_cells += 1
            else:
                r[k] = v
        result.append(r)

    return {"rows": result, "filled_cells": filled_cells}
