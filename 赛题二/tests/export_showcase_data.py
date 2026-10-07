# -*- coding: utf-8 -*-
"""导出真实查询结果，供静态展示页使用。

硬性原则：展示页上的每一个数字都必须来自平台真实计算，不得手写。
分工文档 §10：「如实说明模拟数据、测试条件和产品限制」，
§5.4：「页面、演示视频、PPT 和真实产品功能保持一致」。

用法：
    python tests/export_showcase_data.py                # 内置 85k 演示数据 → docs/展示数据.json
    python tests/export_showcase_data.py --source formal # 正式联调库 demo-v1.1 → docs/展示数据-formal.json

两份数据口径一致、数字独立（DS-001）：同一场演示只用一套，禁止混用。
"""

from __future__ import annotations

import argparse
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
from formal_dataset import (FORMAL_COVERAGE_MONTHS, FORMAL_VERSION,  # noqa: E402
                            load_formal_demo)

#: mock 版临时路径被 page_render_test 读取校验展示页数字，两版必须分开
OUT_PATHS = {
    "mock": ["C:\\Windows\\Temp\\_showcase_data.json",
             ROOT / "docs" / "展示数据.json"],
    "formal": ["C:\\Windows\\Temp\\_showcase_data_formal.json",
               ROOT / "docs" / "展示数据-formal.json"],
}


def pick(resp, key_dim, key_val):
    return {r[key_dim]: r[key_val] for r in resp["data"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="导出展示页数据")
    parser.add_argument("--source", choices=("mock", "formal"), default="mock",
                        help="mock=内置 85k 演示数据；formal=正式联调库 demo-v1.1")
    args = parser.parse_args()

    if args.source == "formal":
        tables = load_formal_demo()
        kw = dict(tables=tables, dataset_version=FORMAL_VERSION,
                  coverage_months=FORMAL_COVERAGE_MONTHS)
        quality_version = FORMAL_VERSION
        source_note = (f"正式联调库 {FORMAL_VERSION}（成员 1 交付，2026-01 ~ 2026-09，"
                       "页面管线与 expected.json 逐分一致）")
    else:
        tables = demo_tables()
        kw = {}
        quality_version = "mock-v1.0-demo"
        source_note = "内置演示数据（85,018 单，2026-06 ~ 2026-09）"

    data: dict = {"source": args.source, "source_note": source_note}

    # 1) 9 月 / 8 月分地区净销售额 + 环比
    sep = mock_backend.handle("2026年9月各地区的净销售额", **kw)
    aug = mock_backend.handle("2026年8月各地区的净销售额", **kw)
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
        "net_sales": mock_backend.handle("2026年9月华东地区的净销售额", **kw)["data"][0]["net_sales"],
        "paid_amount": mock_backend.handle("2026年9月华东地区的实付金额", **kw)["data"][0]["paid_amount"],
        "refund_amount": mock_backend.handle("2026年9月华东地区的成功退款金额", **kw)["data"][0]["refund_amount"],
        "paid_order_count": mock_backend.handle("2026年9月华东地区的支付订单数", **kw)["data"][0]["paid_order_count"],
        "paid_customer_count": mock_backend.handle("2026年9月华东地区的支付人数", **kw)["data"][0]["paid_customer_count"],
    }
    data["sep_total_net_sales"] = mock_backend.handle("2026年9月的净销售额", **kw)["data"][0]["net_sales"]

    # 3) 澄清往返（真实调用）
    r1 = mock_backend.handle("9月的销售额是多少", **kw)
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
        **kw)
    data["clarify_round2"] = {
        "status": r2["status"], "metric": r2["metric"],
        "definition": r2["definition"], "unit": r2["unit"],
        "value": r2["data"][0]["net_sales"],
        "source_tables": r2["source_tables"],
        "dataset_version": r2["dataset_version"],
        "sql": r2["generated_sql"],
    }

    # 4) 因果问题（数据不足）
    causal = mock_backend.handle("为什么华东地区9月净销售额下降了", **kw)
    data["causal"] = {k: causal.get(k) for k in
                      ("status", "message", "reason", "missing", "suggestion", "retryable")}

    # 5) 质检对照
    clean = quality.inspect_datasets(tables, version=quality_version)
    dirty = quality.inspect_datasets(anomaly_tables(tables), version="anomaly-test")
    data["quality"] = {
        "clean": {"errors": clean["total_errors"], "warnings": clean["total_warnings"],
                  "tables": [{"name": t["name"], "rows": t["rows"]} for t in clean["tables"]]},
        "dirty": {"errors": dirty["total_errors"], "warnings": dirty["total_warnings"],
                  "issues": dirty["issues"]},
    }

    text = json.dumps(data, ensure_ascii=False, indent=2)
    for p in OUT_PATHS[args.source]:
        Path(p).write_text(text, encoding="utf-8", newline="\n")
    print(f"[{args.source}] exported to:")
    for p in OUT_PATHS[args.source]:
        print(f"  {p}")


if __name__ == "__main__":
    main()
