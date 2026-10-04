# -*- coding: utf-8 -*-
"""IS-001 决策支撑：净销售额中退款时间归属的两种口径对比（截止 2026-10-08）。

两种口径（除归属列外，聚合逻辑完全相同，均排除 failed / 均按 order_id 预聚合）：

  方案 A（现行 S2 / contracts.py）：退款按 **refund_time** 归属期间
      净销售额_M = 期间 M 成功支付金额 - 期间 M 成功完成退款金额
  方案 B（S1 明细直连的默认行为）：退款按订单 **pay_time** 归属期间
      净销售额_M = 期间 M 成功支付金额 - 这些订单的全部成功退款（含以后月份退的）

数据：demo_data.cross_month_refund_tables() —— 把华东 8 月订单的 5 笔大额
成功退款移动到 2026-09-03，退款总额守恒，仅改变归属月份。

产出：
  tests/_IS001口径对比.csv   各月 × 各地区两种口径数值与差异
  tests/_is001_out.txt       摘要（可直接贴进三人确认文档）

用法：
    python tests/is001_refund_timing.py                 # 85k 演示数据 + 跨月退款注入变体
    python tests/is001_refund_timing.py --source formal # 正式库 demo-v1.1 真实跨月退款测量

--source formal 不做人工注入：直接测量正式库中自然存在的跨月退款（退款月≠订单支付月）
规模与占比，并计算方案 B 在真实数据上对历史月份的回溯漂移量。
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from demo_data import cross_month_refund_tables, demo_tables  # noqa: E402
from formal_dataset import FORMAL_COVERAGE_MONTHS, FORMAL_VERSION, load_formal_demo  # noqa: E402

MONTHS_MOCK = ["2026-06", "2026-07", "2026-08", "2026-09"]
REGIONS = ["华东", "华南", "华北", "西南", "华中"]
LINES: list = []


def log(msg: str = "") -> None:
    LINES.append(str(msg))
    OUT_TXT.write_text("\n".join(LINES), encoding="utf-8")


def _base_frames(tables: dict, region_from_orders: bool = False):
    orders = tables["orders"].copy()
    refunds = tables["refunds"].copy()
    orders["pay_time"] = pd.to_datetime(orders["pay_time"], errors="coerce")
    refunds["refund_time"] = pd.to_datetime(refunds["refund_time"], errors="coerce")
    orders = orders[orders["pay_status"] == "success"]
    if region_from_orders:
        # 正式库：地区是订单快照，直接随行保留（不提升到客户维度）
        orders = orders[["order_id", "customer_id", "region", "pay_time", "pay_amount"]]
    else:
        customers = tables["customers"][["customer_id", "region"]].copy()
        orders = orders.merge(customers, on="customer_id")
    refunds = refunds[refunds["refund_status"] == "success"].merge(
        orders[["order_id", "region", "pay_time"]], on="order_id")
    return orders, refunds


def net_sales_matrix(tables: dict, attr: str, months: list,
                     region_from_orders: bool = False) -> pd.DataFrame:
    """返回 月份×地区 净销售额矩阵。

    attr='refund_time'：退款计入退款发生月（方案 A）
    attr='pay_time'    ：退款计入订单支付月（方案 B）
    """
    orders, refunds = _base_frames(tables, region_from_orders)
    paid = (orders.assign(m=orders["pay_time"].dt.to_period("M").astype(str))
            .groupby(["m", "region"])["pay_amount"].sum())
    refunds = refunds.assign(
        m=refunds[attr].dt.to_period("M").astype(str))
    # 先按 order_id 预聚合到（归属月, 地区），杜绝一单多退重复累计
    ref_pre = refunds.groupby(["m", "region", "order_id"])["refund_amount"].sum()
    ref = ref_pre.groupby(level=["m", "region"]).sum()
    net = paid.sub(ref, fill_value=0).round(2)
    mat = net.unstack("region").reindex(index=months, columns=REGIONS).fillna(0.0)
    mat.index.name = "月份"
    return mat


def main_mock() -> None:
    global OUT_CSV, OUT_TXT
    OUT_CSV = ROOT / "tests" / "_IS001口径对比.csv"
    OUT_TXT = ROOT / "tests" / "_is001_out.txt"
    months = MONTHS_MOCK
    log("=" * 78)
    log("IS-001 净销售额退款时间归属 · 两种口径对比（85k 内置演示数据 + 注入变体）")
    log("=" * 78)

    base = demo_tables()
    variant = cross_month_refund_tables(base)
    info = variant["_cross_month_moves"]
    log(f"\n跨月退款注入：{info['count']} 笔，合计 {info['amount']:,.2f} 元")
    log("（华东 2026-08 支付订单的成功退款，refund_time 移至 2026-09-03；退款总额守恒）")
    for mv in info["moves"]:
        log(f"  {mv['refund_id']} 订单 {mv['order_id']}  {mv['refund_amount']:>10,.2f} 元  "
            f"{mv['old_refund_time']} -> {mv['new_refund_time']}")

    mat_a = net_sales_matrix(variant, "refund_time", months)
    mat_b = net_sales_matrix(variant, "pay_time", months)
    diff = (mat_a - mat_b).round(2)

    log("\n方案 A（refund_time 归属，现行 S2）：")
    log(mat_a.to_string(float_format=lambda x: f"{x:>12,.2f}"))
    log("\n方案 B（pay_time 归属，S1 直连默认）：")
    log(mat_b.to_string(float_format=lambda x: f"{x:>12,.2f}"))
    log("\n差异 A - B（正数=按退款月归属时该月净销售额更低）：")
    log(diff.to_string(float_format=lambda x: f"{x:>12,.2f}"))

    # 守恒校验：差异只应出现在 8、9 月华东，且金额精确等于移动额、方向相反
    changed = [(m, r, diff.loc[m, r]) for m in months for r in REGIONS
               if abs(diff.loc[m, r]) > 0.01]
    aug = diff.loc["2026-08", "华东"]
    sep = diff.loc["2026-09", "华东"]
    checks = [
        ("只有 2026-08 / 2026-09 华东出现差异",
         set((m, r) for m, r, _ in changed) == {("2026-08", "华东"), ("2026-09", "华东")}),
        ("8 月差异为 +移动额（退款移出当月，当月净销售额升高）",
         abs(aug - info["amount"]) < 0.01),
        ("9 月差异为 -移动额（退款计入次月，次月净销售额降低）",
         abs(sep + info["amount"]) < 0.01),
        ("两口径全期合计相等（退款只是换月，不改变总额）",
         abs(mat_a.values.sum() - mat_b.values.sum()) < 0.01),
    ]
    log("\n守恒校验：")
    for desc, ok in checks:
        log(f"  [{'PASS' if ok else 'FAIL'}] {desc}")

    # 干净数据上两口径应完全无差异（证明实验装置本身不引入偏差）
    mat_a0 = net_sales_matrix(base, "refund_time", months)
    mat_b0 = net_sales_matrix(base, "pay_time", months)
    clean_ok = (mat_a0 - mat_b0).abs().max().max() < 0.01
    log(f"  [{'PASS' if clean_ok else 'FAIL'}] 干净数据上两口径完全一致"
        f"（最大差异 {(mat_a0 - mat_b0).abs().max().max():.2f}）")

    _write_csv(mat_a, mat_b, diff, months)

    log("\n" + "-" * 78)
    log("给三人确认会的结论建议（成员 3 起草，非最终决定）：")
    log("1. 推荐方案 A（refund_time 归属）：净销售额衡量「期间内实际沉淀的收入」，")
    log("   退款是当月发生的现金流出，与支付行为解耦；跨月退款不会追溯改写已结账月份。")
    log("2. 方案 B 的业务代价：9 月发生的退款会回头修改 8 月报表，历史月份数字随退款")
    log("   持续漂移，已发布的月度结论无法冻结，违背「结果可追溯、口径不变化」的目标。")
    log("3. 方案 A 的注意点：当月支付、次月才退的订单，当月净销售额暂时偏高；")
    log("   需在结果依据页保留「退款按退款完成时间归属」的明示口径（contracts 已具备）。")
    log("4. 正式库 demo-v1.1 的真实跨月退款占比见 --source formal 测量结果。")
    log("=" * 78)

    if not all(ok for _, ok in checks) or not clean_ok:
        sys.exit(1)


def main_formal() -> None:
    global OUT_CSV, OUT_TXT
    OUT_CSV = ROOT / "tests" / "_IS001口径对比_formal.csv"
    OUT_TXT = ROOT / "tests" / "_is001_formal_out.txt"
    months = FORMAL_COVERAGE_MONTHS
    tables = load_formal_demo()

    log("=" * 78)
    log(f"IS-001 净销售额退款时间归属 · 正式库 {FORMAL_VERSION} 真实跨月退款测量")
    log("=" * 78)

    # ---- 真实跨月退款测量：成功退款中 refund_time 月 != 订单 pay_time 月 ----
    orders, refunds = _base_frames(tables, region_from_orders=True)
    refunds["pay_m"] = refunds["pay_time"].dt.to_period("M").astype(str)
    refunds["ref_m"] = refunds["refund_time"].dt.to_period("M").astype(str)
    cross = refunds[refunds["pay_m"] != refunds["ref_m"]]
    total_ref_count = len(refunds)
    total_ref_amount = round(refunds["refund_amount"].sum(), 2)
    cross_count = len(cross)
    cross_amount = round(cross["refund_amount"].sum(), 2)
    log(f"\n成功退款总数：{total_ref_count:,} 笔，合计 {total_ref_amount:,.2f} 元")
    log(f"其中跨月退款：{cross_count:,} 笔（{cross_count / total_ref_count:.2%}），"
        f"合计 {cross_amount:,.2f} 元（{cross_amount / total_ref_amount:.2%}）")
    log("跨月方向分布（支付月 → 退款月，前 10）：")
    dist = (cross.groupby(["pay_m", "ref_m"])["refund_amount"]
            .agg(["count", "sum"]).sort_values("sum", ascending=False).head(10))
    for (pm, rm), row in dist.iterrows():
        log(f"  {pm} → {rm}  {int(row['count']):>3} 笔  {row['sum']:>12,.2f} 元")

    mat_a = net_sales_matrix(tables, "refund_time", months, region_from_orders=True)
    mat_b = net_sales_matrix(tables, "pay_time", months, region_from_orders=True)
    diff = (mat_a - mat_b).round(2)

    log("\n方案 A（refund_time 归属，现行 S2）：")
    log(mat_a.to_string(float_format=lambda x: f"{x:>13,.2f}"))
    log("\n方案 B（pay_time 归属，S1 直连默认）：")
    log(mat_b.to_string(float_format=lambda x: f"{x:>13,.2f}"))
    log("\n差异 A - B（真实跨月退款造成的历史月份回溯漂移）：")
    log(diff.to_string(float_format=lambda x: f"{x:>13,.2f}"))

    changed = [(m, r, float(diff.loc[m, r])) for m in months for r in REGIONS
               if abs(diff.loc[m, r]) > 0.01]
    log(f"\n受影响单元格：{len(changed)} / {len(months) * len(REGIONS)}")
    biggest = max(changed, key=lambda x: abs(x[2]), default=None)
    if biggest:
        log(f"最大单格漂移：{biggest[0]} {biggest[1]} {biggest[2]:,.2f} 元")
    # 9 月华东漂移（演示主问题直接相关）
    sep_east = float(diff.loc["2026-09", "华东"])
    sep_east_a = float(mat_a.loc["2026-09", "华东"])
    if abs(sep_east) > 0.01:
        log(f"2026-09 华东：方案 A {sep_east_a:,.2f} 元，方案 B 回溯改写 "
            f"{sep_east:,.2f} 元（{sep_east / sep_east_a:.2%}）")

    # 独立重算：按退款明细逐笔构造差异（支付月 +额、退款月 -额），
    # 单元格层面的双向抵消会自然发生，必须与 A-B 矩阵逐格相等
    signed = pd.concat([
        cross.assign(m=cross["pay_m"], delta=cross["refund_amount"])[["m", "region", "delta"]],
        cross.assign(m=cross["ref_m"], delta=-cross["refund_amount"])[["m", "region", "delta"]],
    ])
    rebuilt = (signed.groupby(["m", "region"])["delta"].sum()
               .unstack("region").reindex(index=months, columns=REGIONS).fillna(0.0).round(2))
    checks = [
        ("两口径全期合计相等（退款只是换月，不改变总额）",
         abs(mat_a.values.sum() - mat_b.values.sum()) < 0.01),
        ("差异矩阵行列求和自洽（漂移有来源也有去向）",
         abs(diff.values.sum()) < 0.01),
        ("A-B 差异 = 逐笔跨月退款独立重算（含同月对双向抵消）",
         (diff - rebuilt).abs().max().max() < 0.02),
    ]
    log("\n守恒校验：")
    all_ok = True
    for desc, ok in checks:
        all_ok &= ok
        log(f"  [{'PASS' if ok else 'FAIL'}] {desc}")

    _write_csv(mat_a, mat_b, diff, months)

    log("\n" + "-" * 78)
    log("正式库结论（供 IS-001 三人确认）：")
    log(f"1. 真实数据中跨月退款占比 {cross_count / total_ref_count:.2%}（金额占比 "
        f"{cross_amount / total_ref_amount:.2%}）——并非极端个例，口径选择会实质影响月度数字。")
    log("2. 方案 B 会使历史已结账月份被后续退款持续回溯改写；方案 A 只影响退款发生当月。")
    log("3. 建议维持方案 A（与 contracts.py、成员 1 执行层、页面管线现行实现一致）。")
    log("=" * 78)

    if not all_ok:
        sys.exit(1)


def _write_csv(mat_a, mat_b, diff, months) -> None:
    # 写 CSV
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["月份", "地区", "方案A_refund_time归属", "方案B_pay_time归属", "差异A-B"])
        for m in months:
            for r in REGIONS:
                w.writerow([m, r, round(mat_a.loc[m, r], 2),
                            round(mat_b.loc[m, r], 2), round(diff.loc[m, r], 2)])
    log(f"\n对比表：{OUT_CSV}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IS-001 退款时间归属两口径对比")
    parser.add_argument("--source", choices=("mock", "formal"), default="mock")
    args = parser.parse_args()
    (main_formal if args.source == "formal" else main_mock)()
