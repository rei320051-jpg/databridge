"""Example operations agent: consume the same trusted gateway as the page."""

from __future__ import annotations

import re

from shared.contracts import Metric, Status


def monthly_brief(workflow, request: str) -> dict:
    """Produce a factual regional net-sales MoM brief from one trusted query."""
    match = re.search(r"(20\d{2})年(\d{1,2})月", request or "")
    if not match:
        return {"status": Status.NEED_CLARIFICATION,
                "message": "请指定年份和月份，例如“生成2026年9月经营简报”。"}
    year, month = map(int, match.groups())
    if not 1 <= month <= 12:
        return {"status": Status.OUT_OF_SCOPE, "message": "月份必须在 1 至 12 之间。"}
    question = f"{year}年{month}月各地区净销售额环比"
    response = workflow.run({"question": question})
    if response["status"] != Status.SUCCESS:
        return {"status": response["status"], "message": response["message"],
                "source_response": response}
    rows = response["data"]
    if response["metric"] != Metric.NET_SALES or response["group_by"] != ["region"] or not rows:
        return {"status": Status.INSUFFICIENT_DATA,
                "message": "缺少各地区净销售额数据，无法形成经营简报。",
                "source_response": response}
    # Match member 3's showcase: "下降幅度" means percentage, not absolute fen.
    declines = [row for row in rows if row.get("growth_rate") is not None and row["growth_rate"] < 0]
    worst = min(declines, key=lambda row: row["growth_rate"]) if declines else None
    headline = (f"环比降幅最大的地区是{worst['region']}，下降{abs(worst['growth_rate']) * 100:.2f}%"
                f"（减少{abs(worst['difference']):.2f}元）。" if worst else
                "没有可计算的净销售额环比下降地区；基期不大于零时增长率不作比较。")
    text = (f"{year}年{month}月经营简报：已核对 {len(rows)} 个地区的净销售额及环比。"
            f"{headline}本简报只描述指标变化，不能推断变化原因。")
    return {"status": Status.SUCCESS, "brief": text, "largest_decline": worst,
            "regions": rows, "metric": response["metric"],
            "definition": response["definition"], "unit": response["unit"],
            "source_tables": response["source_tables"], "dataset_version": response["dataset_version"],
            "query_id": response["query_id"], "warnings": response["warnings"],
            "limitations": ["模拟数据不代表真实经营", "仅能描述指标变化，不能判断因果原因"],
            "plan": response["plan"]}
