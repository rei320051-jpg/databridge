# -*- coding: utf-8 -*-
"""跨团队一致性测试：页面 mock 管线在成员 1 正式联调库（data/demo, demo-v1.0）上的
计算结果，必须与成员 1 随库交付的 expected.json 标准答案逐分一致。

这是 F07「页面与外部 Agent 对同一问题得到相同结果」在数据集统一（DS-001）过程中的
自动化锚点：同一份 CSV，经适配层转换后由页面参考实现计算，与成员 1 SQLite 执行层
各自独立聚合，结果必须相同。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mock_backend  # noqa: E402
from formal_dataset import (  # noqa: E402
    FORMAL_COVERAGE_MONTHS, FORMAL_VERSION, cross_region_customers,
    formal_expected, load_formal_demo,
)

#: 页面管线在正式库上的统一调用参数（版本 + 显式覆盖区间）
KW = dict(tables=None, dataset_version=FORMAL_VERSION,
          coverage_months=FORMAL_COVERAGE_MONTHS)

ERRORS = []
OUT = [r"C:\Windows\Temp\_formal_dataset_out.txt",
       ROOT / "tests" / "_formal_dataset_out.txt"]
LINES = []


def log(msg: str = "") -> None:
    LINES.append(str(msg))
    for p in OUT:
        try:
            p.write_text("\n".join(LINES), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


def check(name: str, ok: bool, detail: str = "") -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        ERRORS.append(name)


def _yuan(v_fen) -> float:
    return round(float(v_fen) / 100.0, 2)


def main() -> None:
    log("=" * 78)
    log("正式联调库 demo-v1.0 × 页面管线一致性测试（F07 锚点）")
    log("=" * 78)

    tables = load_formal_demo()
    exp = formal_expected()
    check("三张表均载入", set(tables) == {"orders", "refunds", "customers"},
          str(set(tables)))

    # 物理码 → 对外码的映射完整性
    ps = set(tables["orders"]["pay_status"])
    check("订单状态全部映射为契约码", ps <= {"success", "cancelled", "failed"}, str(ps))
    rs = set(tables["refunds"]["refund_status"])
    check("退款状态保留 success/failed/pending", rs == {"success", "failed", "pending"}, str(rs))
    ct = set(tables["customers"]["customer_type"])
    check("客户类型映射为中文标签", ct == {"新客户", "老客户"}, str(ct))
    check("金额已换算为元（不存在 >10 万的单笔异常分值）",
          float(tables["orders"]["pay_amount"].max()) < 100000,
          f"max={tables['orders']['pay_amount'].max()}")

    # 该数据中大量客户跨地区下单（地区是订单快照而非客户属性），
    # 此检查保证 mock_backend 的快照维度路径真实被覆盖
    n_cross = cross_region_customers()
    log(f"  跨地区下单客户数：{n_cross}（地区必须随订单快照归属，不得取客户单一地区）")
    check("存在跨地区下单客户（快照维度路径被覆盖）", n_cross > 0, str(n_cross))

    # --- 2026-09 全平台月度五指标 vs expected.monthly ---
    m9 = exp["monthly"]["2026-09"]
    got_net = mock_backend.handle(
        "2026年9月的净销售额", tables=tables, dataset_version=FORMAL_VERSION,
        coverage_months=FORMAL_COVERAGE_MONTHS)["data"][0]
    got_paid = mock_backend.handle("2026年9月的实付金额", tables=tables,
                                   coverage_months=FORMAL_COVERAGE_MONTHS)["data"][0]
    got_ref = mock_backend.handle("2026年9月的成功退款金额", tables=tables,
                                  coverage_months=FORMAL_COVERAGE_MONTHS)["data"][0]
    got_orders = mock_backend.handle("2026年9月的支付订单数", tables=tables,
                                     coverage_months=FORMAL_COVERAGE_MONTHS)["data"][0]
    got_cust = mock_backend.handle("2026年9月的支付人数", tables=tables,
                                   coverage_months=FORMAL_COVERAGE_MONTHS)["data"][0]

    check("9月净销售额 == expected", abs(got_net["net_sales"] - _yuan(m9["net_sales"])) < 0.01,
          f"{got_net['net_sales']} vs {_yuan(m9['net_sales'])}")
    check("9月实付金额 == expected", abs(got_paid["paid_amount"] - _yuan(m9["paid_amount"])) < 0.01,
          f"{got_paid['paid_amount']} vs {_yuan(m9['paid_amount'])}")
    check("9月退款金额 == expected", abs(got_ref["refund_amount"] - _yuan(m9["successful_refund_amount"])) < 0.01,
          f"{got_ref['refund_amount']} vs {_yuan(m9['successful_refund_amount'])}")
    check("9月支付订单数 == expected", got_orders["paid_order_count"] == m9["paid_orders"],
          f"{got_orders['paid_order_count']} vs {m9['paid_orders']}")
    check("9月支付人数 == expected", got_cust["paid_customer_count"] == m9["paying_customers"],
          f"{got_cust['paid_customer_count']} vs {m9['paying_customers']}")

    # --- 9 月分地区五指标 vs expected.september_by_region ---
    def _region(question, key):
        rows = mock_backend.handle(question, tables=tables, coverage_months=FORMAL_COVERAGE_MONTHS)["data"]
        return {r["region"]: r[key] for r in rows}

    net_r = _region("2026年9月各地区的净销售额", "net_sales")
    paid_r = _region("2026年9月各地区的实付金额", "paid_amount")
    ref_r = _region("2026年9月各地区的成功退款金额", "refund_amount")
    ord_r = _region("2026年9月各地区的支付订单数", "paid_order_count")
    cust_r = _region("2026年9月各地区的支付人数", "paid_customer_count")

    for region, e in exp["september_by_region"].items():
        check(f"{region} 净销售额", abs(net_r.get(region, 0) - _yuan(e["net_sales"])) < 0.01,
              f"{net_r.get(region)} vs {_yuan(e['net_sales'])}")
        check(f"{region} 实付金额", abs(paid_r.get(region, 0) - _yuan(e["paid_amount"])) < 0.01,
              f"{paid_r.get(region)} vs {_yuan(e['paid_amount'])}")
        check(f"{region} 退款金额", abs(ref_r.get(region, 0) - _yuan(e["successful_refund_amount"])) < 0.01,
              f"{ref_r.get(region)} vs {_yuan(e['successful_refund_amount'])}")
        check(f"{region} 支付订单数", ord_r.get(region) == e["paid_orders"],
              f"{ord_r.get(region)} vs {e['paid_orders']}")
        check(f"{region} 支付人数", cust_r.get(region) == e["paying_customers"],
              f"{cust_r.get(region)} vs {e['paying_customers']}")

    # 分组之和 == 汇总值（防丢行/重复累计，在正式库上同样成立）
    check("分地区净销售额之和 == 全平台",
          abs(sum(net_r.values()) - _yuan(m9["net_sales"])) < 0.01,
          f"{sum(net_r.values()):.2f} vs {_yuan(m9['net_sales']):.2f}")

    # --- 数据覆盖：正式库 1–9 月，3 月可答；页面内置演示数据 6–9 月，3 月拒答 ---
    r_mar = mock_backend.handle("2026年3月的净销售额", tables=tables, coverage_months=FORMAL_COVERAGE_MONTHS)
    check("正式库覆盖 2026-03，返回 success", r_mar["status"] == "success", r_mar.get("status"))
    check("3月净销售额 == expected",
          abs(r_mar["data"][0]["net_sales"] - _yuan(exp["monthly"]["2026-03"]["net_sales"])) < 0.01)

    # --- 正式库自身质量：无超额退款（与成员 1 导入器同一条硬规则）---
    import pandas as pd
    ok_orders = tables["orders"][tables["orders"]["pay_status"] == "success"][["order_id", "pay_amount"]]
    ref_sum = (tables["refunds"][tables["refunds"]["refund_status"] == "success"]
               .groupby("order_id")["refund_amount"].sum())
    cmp_df = ref_sum.to_frame("r").join(ok_orders.set_index("order_id")["pay_amount"])
    n_over = int((cmp_df["r"] > cmp_df["pay_amount"] + 0.005).sum())
    check("正式库无超额退款订单", n_over == 0, f"{n_over} 单超额")

    log("\n" + "=" * 78)
    if ERRORS:
        log("结论：发现 " + str(len(ERRORS)) + " 项不一致：" + "；".join(ERRORS))
        raise SystemExit(1)
    log("结论：页面管线与成员 1 正式库 expected.json 全部一致（含分地区 20 项核对）。")
    log("=" * 78)


if __name__ == "__main__":
    main()

