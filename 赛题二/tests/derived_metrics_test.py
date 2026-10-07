# -*- coding: utf-8 -*-
"""派生指标测试（口径冻结确认单 2026-10-04，DM-001~006）。

覆盖：
  DM-001 三个派生指标首版全上；DM-002 退款率分母用实付金额；
  DM-003 metric_kind=ratio + components 分子分母溯源；
  DM-004 「人均消费」必须澄清，候选顺序 [支付人均消费, 客单价]；
  DM-005 比率 2 位百分比、分母为零返回 null（不是 0）+ 警告；
  DM-006 复购率继续拒答；
  铁律：先汇总分子分母再相除；分组比率不可平均回整体；分子分母同筛选。
正式库锚点：9 月华东退款率 = 955,887.84 / 7,786,231.39。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)

import mock_backend  # noqa: E402
from demo_data import demo_tables  # noqa: E402
from formal_dataset import FORMAL_COVERAGE_MONTHS, FORMAL_VERSION, load_formal_demo  # noqa: E402
from shared.contracts import METRIC_SPEC, Metric, Status  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" —— {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def expect(cond: bool, name: str, detail: str = "") -> None:
    check(name, cond, detail)


def components_ok(resp: dict) -> bool:
    comp = resp.get("components") or {}
    return (resp.get("metric_kind") == "ratio"
            and {"numerator_metric", "denominator_metric"} <= set(comp))


# ---------------------------------------------------------------------------
# 内置 85k 数据
# ---------------------------------------------------------------------------
tables = demo_tables()
kw = dict(tables=tables)

# 基础分量（独立 pandas 计算，不复用被测函数）
o = tables["orders"]
r = tables["refunds"]
cust = tables["customers"].set_index("customer_id")["region"]
o9 = o[(o["pay_status"] == "success") & (o["pay_time"].str[:7] == "2026-09")].copy()
o9["region"] = o9["customer_id"].map(cust)
r9 = r[(r["refund_status"] == "success") & (r["refund_time"].str[:7] == "2026-09")]
paid_total = round(o9["pay_amount"].sum(), 2)
ref_total = round(r9["refund_amount"].sum(), 2)
ord_total = o9["order_id"].nunique()
cus_total = o9["customer_id"].nunique()

# 1) 契约规格
expect(Metric.REFUND_RATE in METRIC_SPEC and Metric.AVG_ORDER_VALUE in METRIC_SPEC
       and Metric.PAID_PER_CUSTOMER in METRIC_SPEC, "DM-001 三个派生指标已进 METRIC_SPEC")
expect(METRIC_SPEC[Metric.REFUND_RATE]["denominator"] == Metric.PAID_AMOUNT,
       "DM-002 退款率分母是实付金额（不是净销售额）")
for code in (Metric.REFUND_RATE, Metric.AVG_ORDER_VALUE, Metric.PAID_PER_CUSTOMER):
    expect(METRIC_SPEC[code].get("kind") == "ratio", f"{code} 标记 metric_kind=ratio")

# 2) 全平台退款率 = 退款 / 实付，百分比 2 位
resp = mock_backend.handle("2026年9月的退款率", **kw)
expected_rate = round(ref_total / paid_total * 100, 2)
expect(resp["status"] == Status.SUCCESS, "9月退款率查询成功", str(resp.get("status")))
expect(abs(resp["data"][0]["refund_rate"] - expected_rate) < 0.005,
       f"退款率={resp['data'][0].get('refund_rate')}% 预期≈{expected_rate}%")
expect(components_ok(resp), "DM-003 信封带 metric_kind=ratio 与 components")
expect(resp["unit"] == "%", "退款率单位为 %", resp.get("unit", ""))

# 3) 客单价 / 支付人均消费
aov = mock_backend.handle("2026年9月的客单价", **kw)
expect(aov["status"] == Status.SUCCESS and abs(
    aov["data"][0]["avg_order_value"] - round(paid_total / ord_total, 2)) < 0.005,
       "客单价 = 实付金额 / 支付订单数")
ppc = mock_backend.handle("2026年9月的支付人均消费", **kw)
expect(ppc["status"] == Status.SUCCESS and abs(
    ppc["data"][0]["paid_per_customer"] - round(paid_total / cus_total, 2)) < 0.005,
       "支付人均消费 = 实付金额 / 支付人数")

# 4) 分组退款率：组内用自己的分子分母；行内含 components 分量值
grp = mock_backend.handle("2026年9月各地区的退款率", **kw)
expect(grp["status"] == Status.SUCCESS and len(grp["data"]) == 5, "分地区退款率返回 5 行")
rates = {row["region"]: row for row in grp["data"]}
for row in grp["data"]:
    nv, dv = row.get("numerator_value"), row.get("denominator_value")
    expect(nv is not None and dv is not None and dv > 0
           and abs(row["refund_rate"] - round(nv / dv * 100, 2)) < 0.005,
           f"{row['region']} 退款率由行内分子分母现场相除")
# 独立验证华东一行
o9e = o9[o9["region"] == "华东"]
r9e = r9[r9["order_id"].isin(set(o9e["order_id"]))]
exp_east = round(r9e["refund_amount"].sum() / o9e["pay_amount"].sum() * 100, 2)
expect(abs(rates["华东"]["refund_rate"] - exp_east) < 0.005,
       f"华东退款率={rates['华东']['refund_rate']} 独立计算={exp_east}")
# 铁律：分组比率不可平均回整体（先汇总再相除）
avg_of_rates = round(sum(row["refund_rate"] for row in grp["data"]) / 5, 4)
expect(abs(avg_of_rates - resp["data"][0]["refund_rate"]) > 0.001,
       f"组率算术平均 {avg_of_rates}% ≠ 整体率 {resp['data'][0]['refund_rate']}%（不可平均）")
sum_num = sum(row["numerator_value"] for row in grp["data"])
sum_den = sum(row["denominator_value"] for row in grp["data"])
expect(abs(round(sum_num / sum_den * 100, 2) - resp["data"][0]["refund_rate"]) < 0.01,
       "各组分子分母分别汇总后再相除 = 整体率")

# 5) 筛选同施加于分子分母（华东客单价）
aov_e = mock_backend.handle("2026年9月华东地区的客单价", **kw)
expect(aov_e["status"] == Status.SUCCESS and abs(
    aov_e["data"][0]["avg_order_value"]
    - round(o9e["pay_amount"].sum() / o9e["order_id"].nunique(), 2)) < 0.005,
    "筛选条件同时施加于客单价分子与分母")

# 6) DM-004 「人均消费」必须澄清，顺序 [支付人均消费, 客单价]
clr = mock_backend.handle("2026年9月的人均消费", **kw)
expect(clr["status"] == Status.NEED_CLARIFICATION, "「人均消费」触发澄清", str(clr.get("status")))
choices = [o["value"] for o in clr["clarification"]["options"]]
expect(choices == [Metric.PAID_PER_CUSTOMER, Metric.AVG_ORDER_VALUE],
       f"候选顺序 {choices}")
clr2 = mock_backend.handle(
    "2026年9月的人均消费",
    context=clr["clarification"]["resolved_context"],
    clarification={"id": clr["clarification"]["id"], "target_field": "metric",
                   "choice": Metric.PAID_PER_CUSTOMER, "free_text": None}, **kw)
expect(clr2["status"] == Status.SUCCESS, "澄清后选支付人均消费可成功查询")

# 7) DM-006 复购率继续拒答
deny = mock_backend.handle("2026年9月的复购率是多少", **kw)
expect(deny["status"] == Status.OUT_OF_SCOPE and deny["reason"] == "derived_metric_unsupported",
       "复购率仍明确拒答")

# 8) DM-005 零分母 → null + 警告，不返回 0
zero_tables = {
    "customers": pd.DataFrame([{"customer_id": "C1", "region": "华东",
                                "customer_type": "新客户", "register_date": "2026-01-01"}]),
    "orders": pd.DataFrame([{
        "order_id": "O1", "customer_id": "C1", "region": "华东", "customer_type": "新客户",
        "order_time": "2026-09-02 10:00:00", "pay_time": "2026-09-02 10:00:00",
        "pay_status": "failed", "pay_amount": 0.0}]),
    "refunds": pd.DataFrame([{
        "refund_id": "RF1", "order_id": "O1",
        "refund_time": "2026-09-03 10:00:00", "refund_status": "success",
        "refund_amount": 50.0}]),
}
z = mock_backend.handle("2026年9月的退款率", tables=zero_tables)
expect(z["status"] == Status.SUCCESS and z["data"][0]["refund_rate"] is None,
       "零分母时退款率为 null（不是 0）")
expect(any(w["code"] == "NON_POSITIVE_DENOMINATOR" for w in z.get("warnings", [])),
       "零分母附带 NON_POSITIVE_DENOMINATOR 警告")

# 9) 正式库锚点：9 月华东退款率
ft = load_formal_demo()
fkw = dict(tables=ft, dataset_version=FORMAL_VERSION, coverage_months=FORMAL_COVERAGE_MONTHS)
fe = mock_backend.handle("2026年9月华东地区的退款率", **fkw)
exp_fe = round(955887.84 / 7786231.39 * 100, 2)
expect(fe["status"] == Status.SUCCESS and abs(fe["data"][0]["refund_rate"] - exp_fe) < 0.005,
       f"正式库9月华东退款率={fe['data'][0].get('refund_rate') if fe['status']==Status.SUCCESS else fe.get('reason')} 预期 {exp_fe}")
expect(fe.get("dataset_version") == FORMAL_VERSION, "正式库查询带 demo-v1.1 版本号")

print("\n" + ("全部通过。" if not FAILURES else f"{len(FAILURES)} 项失败：{FAILURES}"))
sys.exit(1 if FAILURES else 0)
