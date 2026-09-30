# -*- coding: utf-8 -*-
"""导出真实查询结果，供静态展示页使用。

硬性原则：展示页上的每一个数字都必须来自平台真实计算，不得手写。
分工文档 §10：「如实说明模拟数据、测试条件和产品限制」，
§5.4：「页面、演示视频、PPT 和真实产品功能保持一致」。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)

import mock_backend  # noqa: E402
import quality  # noqa: E402
from demo_data import anomaly_tables, demo_tables  # noqa: E402

OUT = [r"C:\Windows\Temp\_showcase_data.json",
       ROOT / "docs" / "展示数据.json"]


def pick(resp, key_dim, key_val):
    return {r[key_dim]: r[key_val] for r in resp["data"]}


def main() -> None:
    tables = demo_tables()
    data: dict = {}

    # 1) 9 月 / 8 月分地区净销售额 + 环比
    sep = mock_backend.handle("2026年9月各地区的净销售额", tables=tables)
    aug = mock_backend.handle("2026年8月各地区的净销售额", tables=tables)
    sep_map = pick(sep, "region", "net_sales")
    aug_map = pick(aug, "region", "net_sales")
    mom = {r: round((sep_map[r] - aug_map[r]) / aug_map[r] * 100, 2)
           for r in sep_map if aug_map.get(r)}
    data["net_sales_by_region"] = {
        "2026-09": sep_map, "2026-08": aug_map, "mom_pct": mom,
    }
    data["worst_region"] = min(mom, key=mom.get)

    # 2) 华东 9 月四个基础指标
    data["east_sep"] = {
        "net_sales": mock_backend.handle("2026年9月华东地区的净销售额", tables=tables)["data"][0]["net_sales"],
        "paid_amount": mock_backend.handle("2026年9月华东地区的实付金额", tables=tables)["data"][0]["paid_amount"],
        "refund_amount": mock_backend.handle("2026年9月华东地区的成功退款金额", tables=tables)["data"][0]["refund_amount"],
        "paid_order_count": mock_backend.handle("2026年9月华东地区的支付订单数", tables=tables)["data"][0]["paid_order_count"],
        "paid_customer_count": mock_backend.handle("2026年9月华东地区的支付人数", tables=tables)["data"][0]["paid_customer_count"],
    }
    data["sep_total_net_sales"] = mock_backend.handle("2026年9月的净销售额", tables=tables)["data"][0]["net_sales"]

    # 3) 澄清往返（真实调用）
    r1 = mock_backend.handle("9月的销售额是多少", tables=tables)
    data["clarify_round1"] = {
        "status": r1["status"],
        "question": r1["clarification"]["question"],
        "options": r1["clarification"]["options"],
        "id": r1["clarification"]["id"],
        "reason_code": r1["clarification"]["reason_code"],
    }
    r2 = mock_backend.handle(
        "9月的销售额是多少",
        context=r1["clarification"]["resolved_context"],
        clarification={"id": r1["clarification"]["id"],
                       "target_field": "metric", "choice": "net_sales", "free_text": None},
        tables=tables)
    data["clarify_round2"] = {
        "status": r2["status"], "metric": r2["metric"],
        "definition": r2["definition"], "unit": r2["unit"],
        "value": r2["data"][0]["net_sales"],
        "source_tables": r2["source_tables"],
        "dataset_version": r2["dataset_version"],
        "sql": r2["generated_sql"],
    }

    # 4) 因果问题（数据不足）
    causal = mock_backend.handle("为什么华东地区9月净销售额下降了", tables=tables)
    data["causal"] = {k: causal.get(k) for k in
                      ("status", "message", "reason", "missing", "suggestion", "retryable")}

    # 5) 质检对照
    clean = quality.inspect_datasets(tables, version="mock-v1.0-demo")
    dirty = quality.inspect_datasets(anomaly_tables(tables), version="anomaly-test")
    data["quality"] = {
        "clean": {"errors": clean["total_errors"], "warnings": clean["total_warnings"],
                  "tables": [{"name": t["name"], "rows": t["rows"]} for t in clean["tables"]]},
        "dirty": {"errors": dirty["total_errors"], "warnings": dirty["total_warnings"],
                  "issues": dirty["issues"]},
    }

    text = json.dumps(data, ensure_ascii=False, indent=2)
    for p in OUT:
        Path(p).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
