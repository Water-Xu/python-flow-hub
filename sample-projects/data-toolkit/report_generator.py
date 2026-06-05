"""报告生成块。

依赖资源文件：config/settings.json（报告配置，通过 inputs.settings 传入）

入口函数：
  run                — 生成完整的格式化文本报告
  summary_table      — 将数据行渲染为 Markdown 表格
  generate_chart_data — 将分组统计转换为 ECharts 图表配置
"""

from __future__ import annotations

from datetime import datetime


def _get_settings(inputs: dict) -> dict:
    """读取报告配置，优先用 inputs.settings，回退到默认值。"""
    defaults = {
        "max_rows": 10000,
        "default_top_n": 10,
        "currency": "CNY",
        "date_format": "%Y-%m-%d %H:%M:%S",
        "decimal_places": 2,
    }
    settings: dict = inputs.get("settings") or {}
    return {**defaults, **settings}


def run(inputs: dict) -> dict:
    """生成完整的数据分析文本报告。

    inputs:
      title (str, 可选): 报告标题，默认"数据分析报告"
      stats (dict, 可选): 来自 stats_engine.run 的统计结果
      groups (dict, 可选): 来自 stats_engine.group_by 的分组结果
      correlation (float, 可选): 来自 stats_engine.correlation 的相关系数
      interpretation (str, 可选): 相关性描述
      row_count (int, 可选): 数据总行数
      settings (dict, 可选): 来自 config/settings.json 的配置

    returns:
      report (str): 格式化文本报告
      generated_at (str): 生成时间 ISO 格式
      section_count (int): 报告章节数
    """
    settings = _get_settings(inputs)
    title: str = inputs.get("title", "数据分析报告")
    stats: dict = inputs.get("stats") or {}
    groups: dict = inputs.get("groups") or {}
    corr = inputs.get("correlation")
    interp: str = inputs.get("interpretation", "")
    row_count: int = inputs.get("row_count", 0)
    dp: int = int(settings.get("decimal_places", 2))
    currency: str = settings.get("currency", "CNY")
    now_str = datetime.now().strftime(settings.get("date_format", "%Y-%m-%d %H:%M:%S"))

    sections = 0
    lines = [
        "=" * 50,
        f"  {title}",
        f"  生成时间：{now_str}",
        "=" * 50,
        "",
        f"[数据概览]",
        f"  总记录数：{row_count} 条",
        f"  货币单位：{currency}",
        "",
    ]
    sections += 1

    if stats:
        sections += 1
        lines.append("[数值列统计]")
        for col, s in stats.items():
            lines.append(f"  {col}:")
            lines.append(f"    样本数={s['count']}  均值={s['mean']:.{dp}f}  "
                         f"标准差={s['std']:.{dp}f}")
            lines.append(f"    最小={s['min']:.{dp}f}  最大={s['max']:.{dp}f}  "
                         f"合计={s['sum']:.{dp}f}")
        lines.append("")

    if groups:
        sections += 1
        lines.append("[分组汇总]")
        for k, v in groups.items():
            bar_len = int(v / max(groups.values()) * 20) if max(groups.values()) > 0 else 0
            bar = "█" * bar_len
            lines.append(f"  {k:<12} {v:>10.{dp}f}  {bar}")
        lines.append("")

    if corr is not None:
        sections += 1
        lines.append("[相关性分析]")
        col_x = inputs.get("col_x", "X")
        col_y = inputs.get("col_y", "Y")
        lines.append(f"  {col_x} vs {col_y}：r = {corr}  ({interp})")
        lines.append("")

    lines.append("=" * 50)

    return {
        "report": "\n".join(lines),
        "generated_at": datetime.now().isoformat(),
        "section_count": sections,
    }


def summary_table(inputs: dict) -> dict:
    """将数据行渲染为 Markdown 格式的汇总表格。

    inputs:
      rows (list): 数据行列表
      top_n (int, 可选): 最多展示行数，默认取 settings.default_top_n 或 10
      columns (list, 可选): 指定展示哪些列，默认全部
      settings (dict, 可选): 配置（含 default_top_n）

    returns:
      markdown (str): Markdown 格式表格
      row_count (int): 总行数（含未展示部分）
      displayed (int): 实际展示行数
    """
    settings = _get_settings(inputs)
    rows: list[dict] = inputs.get("rows") or []
    top_n: int = int(inputs.get("top_n") or settings.get("default_top_n", 10))
    columns: list[str] | None = inputs.get("columns")

    if not rows:
        return {"markdown": "_无数据_", "row_count": 0, "displayed": 0}

    if not columns:
        columns = list(rows[0].keys())

    display_rows = rows[:top_n]
    header = "| " + " | ".join(str(c) for c in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body_lines = []
    for row in display_rows:
        cells = [str(row.get(c, "")) for c in columns]
        body_lines.append("| " + " | ".join(cells) + " |")

    md = "\n".join([header, separator] + body_lines)
    if len(rows) > top_n:
        md += f"\n\n_（共 {len(rows)} 条，仅展示前 {top_n} 条）_"

    return {"markdown": md, "row_count": len(rows), "displayed": len(display_rows)}


def generate_chart_data(inputs: dict) -> dict:
    """将分组统计结果转换为 ECharts 图表配置对象。

    inputs:
      groups (dict): 分组统计结果 {"分组键": 数值}
      chart_type (str, 可选): bar | pie | line，默认 "bar"
      title (str, 可选): 图表标题
      group_col (str, 可选): 分组列名（用于轴标签）
      agg_col (str, 可选): 聚合列名（用于轴标签）
      settings (dict, 可选): 配置

    returns:
      labels (list): X 轴标签 / 饼图标签
      values (list): 对应数值
      chart_config (dict): ECharts option 对象（可直接传入 setOption）
    """
    settings = _get_settings(inputs)
    groups: dict = inputs.get("groups") or {}
    chart_type: str = inputs.get("chart_type", "bar")
    title: str = inputs.get("title", "数据图表")
    group_col: str = inputs.get("group_col", "分组")
    agg_col: str = inputs.get("agg_col", "数值")

    if not groups:
        return {"labels": [], "values": [], "chart_config": {}}

    sorted_items = sorted(
        groups.items(),
        key=lambda x: -x[1] if isinstance(x[1], (int, float)) else 0
    )
    labels = [str(k) for k, _ in sorted_items]
    values = [v for _, v in sorted_items]

    if chart_type == "pie":
        series_data = [{"name": k, "value": v} for k, v in sorted_items]
        chart_config = {
            "title": {"text": title, "left": "center"},
            "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
            "legend": {"orient": "vertical", "left": "left"},
            "series": [{"type": "pie", "radius": "60%", "data": series_data,
                        "emphasis": {"itemStyle": {"shadowBlur": 10}}}],
        }
    else:
        chart_config = {
            "title": {"text": title},
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": labels, "name": group_col,
                      "axisLabel": {"rotate": 30}},
            "yAxis": {"type": "value", "name": agg_col},
            "series": [{"type": chart_type, "data": values,
                        "itemStyle": {"borderRadius": 4} if chart_type == "bar" else {}}],
        }

    return {"labels": labels, "values": values, "chart_config": chart_config}
