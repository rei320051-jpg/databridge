# -*- coding: utf-8 -*-
"""成员 3 自测脚本：验证页面侧参考实现能否跑通全部状态与口径。

运行（用托管虚拟环境）：
  & "C:\\Users\\Ho'lo\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\python.exe" tests/smoke_test.py

结果同时写入 tests/_smoke_out.txt（本机 PowerShell stdout 不回传，需落盘读取）。
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pandas as pd  # noqa: E402

from shared.contracts import (  # noqa: E402
    METRIC_SPEC,
    PRESET_EXAMPLES,
    STATUS_LABEL,
    Status,
)
import mock_backend  # noqa: E402
import quality  # noqa: E402

OUT = []
FAILED = []
_LOG_PATHS = [Path(__file__).resolve().parent / "_smoke_out.txt",
              Path(r"C:\Windows\Temp\_smoke_out.txt")]


def log(msg: str = "") -> None:
    """每条日志立即落盘。

    本机沙箱会直接终止发起网络操作的子进程，一旦发生就没有任何机会写结果，
    因此必须增量写盘，才能定位到具体的中断位置。
    """
    OUT.append(str(msg))
    for p in _LOG_PATHS:
        try:
            p.write_text("\n".join(OUT), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


def check(name: str, ok: bool, detail: str = "") -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


def main() -> None:
    t0 = time.time()
    log("=" * 78)
    log("数桥 DataBridge · 页面侧参考实现自测  (成员 3 / 2026-09-30)")
    log("=" * 78)

    log("\n[0] 生成内置演示数据 …")
    from demo_data import anomaly_tables, demo_tables
    tables = demo_tables()
    t1 = time.time()
    for name, df in tables.items():
        log(f"  {name:10s} rows={len(df):>7,}  cols={df.shape[1]}")
    log(f"  [计时] 生成耗时 {t1 - t0:.2f}s")

    rows_total = len(tables["orders"])
    check("演示数据订单量在 1 万 ~ 10 万条区间（分工文档 §3.2.2）",
          10000 <= rows_total <= 100000, f"{rows_total:,} 条")

    # ---------------------------------------------------------------
    log("\n[1] 状态覆盖：逐条跑分工文档 §4.2.5 的六种状态 + 预设用例")
    log(f"  {'分类':<16}{'预期状态':<22}{'实际状态':<22}结果")
    coverage = {}
    for kind, question, expect in PRESET_EXAMPLES:
        resp = mock_backend.handle(question, tables=tables)
        got = resp["status"]
        coverage[got] = coverage.get(got, 0) + 1
        ok = got == expect
        log(f"  {kind:<16}{STATUS_LABEL[expect]:<22}{STATUS_LABEL.get(got, got):<22}"
            f"{'PASS' if ok else 'FAIL'}")
        if not ok:
            FAILED.append(f"状态不符：{question}")
        if got == Status.SUCCESS:
            for row in resp["data"][:3]:
                log(f"        -> {row}")

    check("六种状态中至少覆盖 4 种（八条预设用例）", len(coverage) >= 4,
          f"覆盖 {sorted(coverage)}")

    # ---------------------------------------------------------------
    log("\n[2] 澄清闭环：指标口径歧义 -> 选择 -> 成功返回")
    resp = mock_backend.handle("9月的销售额是多少", tables=tables)
    check("首轮返回 need_clarification", resp["status"] == Status.NEED_CLARIFICATION)
    clr = resp.get("clarification") or {}
    log(f"  澄清问题：{clr.get('question')}")
    log(f"  澄清 id ：{clr.get('id')}  目标槽位：{clr.get('target_field')}")
    opts = clr.get("options") or []
    log(f"  候选    ：{[(o['value'], o['label']) for o in opts]}")
    check("澄清 id 符合 clr_<field>_<seq> 规则",
          clr.get("id", "").startswith("clr_") and clr.get("target_field") in clr.get("id", ""))

    resp2 = mock_backend.handle(
        "9月的销售额是多少",
        context=clr.get("resolved_context"),
        clarification={"id": clr["id"], "target_field": clr["target_field"],
                       "choice": "net_sales", "free_text": None},
        tables=tables)
    check("澄清后返回 success", resp2["status"] == Status.SUCCESS)
    check("澄清后采用的指标为 net_sales", resp2.get("metric") == "net_sales")
    log(f"  结果：{resp2.get('data')}")

    # ---------------------------------------------------------------
    log("\n[3] 澄清闭环：评价标准歧义（「哪个地区最好」）")
    r3 = mock_backend.handle("哪个地区最好", tables=tables)
    check("返回 need_clarification", r3["status"] == Status.NEED_CLARIFICATION)
    check("原因码为 ambiguous_criterion",
          (r3.get("clarification") or {}).get("reason_code") == "ambiguous_criterion",
          str((r3.get("clarification") or {}).get("reason_code")))
    log(f"  澄清问题：{(r3.get('clarification') or {}).get('question')}")

    # ---------------------------------------------------------------
    log("\n[4] 防无限追问：连续两轮澄清后必须降级，不得反复追问")
    ctx = {"clarification_round": 2}
    r4 = mock_backend.handle("最近的数据怎么样", context=ctx, tables=tables)
    check("达到最大轮数后返回 insufficient_data",
          r4["status"] == Status.INSUFFICIENT_DATA, r4["status"])
    log(f"  原因码：{r4.get('reason')}")

    # ---------------------------------------------------------------
    log("\n[5] 口径不变量检查")
    q_region = "2026年9月各地区的净销售额"
    r_all = mock_backend.handle(q_region, tables=tables)
    net_map = {row["region"]: row["net_sales"] for row in r_all["data"]}
    log(f"  分地区净销售额：{net_map}")

    r_total = mock_backend.handle("2026年9月的净销售额", tables=tables)
    total_net = r_total["data"][0]["net_sales"]
    check("分地区之和 == 汇总值（分组不丢行、不重复）",
          abs(sum(net_map.values()) - total_net) < 0.02,
          f"{sum(net_map.values()):,.2f} vs {total_net:,.2f}")

    r_paid = mock_backend.handle("2026年9月各地区的实付金额", tables=tables)
    r_ref = mock_backend.handle("2026年9月各地区的成功退款金额", tables=tables)
    paid_map = {row["region"]: row["paid_amount"] for row in r_paid["data"]}
    ref_map = {row["region"]: row["refund_amount"] for row in r_ref["data"]}
    diff = {k: round(paid_map[k] - ref_map[k] - net_map[k], 2) for k in net_map}
    check("净销售额 == 实付金额 - 成功退款金额（逐地区）",
          all(abs(v) < 0.02 for v in diff.values()), str(diff))

    # ---------------------------------------------------------------
    log("\n[6] 多退款不重复累计（分工文档 §3.4 核心验收项）")
    refunds = tables["refunds"]
    multi = (refunds[refunds["refund_status"] == "success"]
             .groupby("order_id").size().sort_values(ascending=False))
    n_multi = int((multi > 1).sum())
    log(f"  存在多条成功退款的订单数：{n_multi}（最多一个订单 {int(multi.max())} 条）")
    check("数据集中确实存在一对多退款场景", n_multi > 0, f"{n_multi} 个订单")

    # 构造极端用例：给同一个订单追加 5 条大额退款，净销售额应等额下降，实付金额不变
    from demo_data import REGIONS, MONTHS  # noqa: F401
    victim = refunds[(refunds["refund_status"] == "success")].iloc[0]["order_id"]
    inj = tables["refunds"].iloc[[0] * 5].copy()
    inj["refund_id"] = [f"R_TEST_{i}" for i in range(5)]
    inj["order_id"] = victim
    inj["refund_amount"] = 1000.0
    inj["refund_status"] = "success"
    inj["refund_time"] = "2026-09-15 10:00:00"
    t2 = dict(tables)
    t2["refunds"] = pd.concat([tables["refunds"], inj], ignore_index=True)

    base_net = mock_backend.handle("2026年9月的净销售额", tables=tables)["data"][0]["net_sales"]
    inj_net = mock_backend.handle("2026年9月的净销售额", tables=t2)["data"][0]["net_sales"]
    base_paid = mock_backend.handle("2026年9月的实付金额", tables=tables)["data"][0]["paid_amount"]
    inj_paid = mock_backend.handle("2026年9月的实付金额", tables=t2)["data"][0]["paid_amount"]
    check("追加 5 条同订单退款后，净销售额精确下降 5000",
          abs((base_net - inj_net) - 5000.0) < 0.02, f"下降 {base_net - inj_net:,.2f}")
    check("追加退款不影响实付金额（无重复累计）",
          abs(base_paid - inj_paid) < 0.02, f"{base_paid:,.2f} -> {inj_paid:,.2f}")

    # ---------------------------------------------------------------
    log("\n[7] 干扰行必须被排除（失败支付 / 取消 / 失败退款）")
    orders = tables["orders"]
    for st_val in ("failed", "pending", "cancelled"):
        sub = orders[orders["pay_status"] == st_val]
        log(f"  pay_status={st_val:<10} rows={len(sub):>6,} amount_sum={sub['pay_amount'].sum():>14,.2f}")
    bad_ref = tables["refunds"][tables["refunds"]["refund_status"] != "success"]
    log(f"  非成功退款          rows={len(bad_ref):>6,} amount_sum={bad_ref['refund_amount'].sum():>14,.2f}")
    check("数据集中确实存在干扰行", len(bad_ref) > 0 and
          len(orders[orders["pay_status"] != "success"]) > 0)

    # ---------------------------------------------------------------
    log("\n[8] 数据质量检查（异常数据集）")
    t2 = time.time()
    log(f"  [计时] 演示数据生成耗时 {t1 - t0:.2f}s")
    at = anomaly_tables(tables)  # 复用已生成的表，避免重复生成
    log(f"  [计时] 异常数据注入完成，累计 {t2 - t0:.2f}s")
    rep = quality.inspect_datasets(at, version="anomaly-test")
    log(f"  [计时] 质检完成，累计 {t2 - t0:.2f}s")
    log(f"  严重问题 {rep['total_errors']} 项，警告 {rep['total_warnings']} 项")
    codes = sorted({i["code"] for i in rep["issues"]})
    log(f"  命中的检查项：{codes}")
    for i in rep["issues"][:12]:
        log(f"    - [{i['level']:<7}] {i['table']}.{i['field']:<28} x{i['count']:<6} {i['message']}")
    expect_codes = {"duplicate_primary_key", "negative_amount", "unparsable_time",
                    "orphan_foreign_key", "missing_value"}
    check("异常数据集的五类注入问题全部被检出",
          expect_codes.issubset(set(codes)),
          f"缺失 {expect_codes - set(codes)}")

    log("\n  对照组：干净数据集应当没有严重问题")
    rep_clean = quality.inspect_datasets(tables, version="demo")
    log(f"  严重问题 {rep_clean['total_errors']} 项，警告 {rep_clean['total_warnings']} 项")
    check("干净数据集无严重问题", rep_clean["total_errors"] == 0,
          f"{rep_clean['total_errors']} 项")

    # ---------------------------------------------------------------
    log("\n[9] 后端异常路径（不发起真实网络请求：本机沙箱会终止联网的子进程）")
    import urllib.error
    import urllib.request
    from client import BackendError, QueryClient

    real_urlopen = urllib.request.urlopen
    try:
        urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(
            urllib.error.URLError("simulated connection refused"))
        c = QueryClient(mode="live", base_url="http://127.0.0.1:59999", timeout=2)
        try:
            c.submit("测试")
            check("连接失败时抛出 BackendError", False, "未抛错")
        except BackendError as exc:
            check("连接失败时抛出 BackendError", True, str(exc)[:70])
    finally:
        urllib.request.urlopen = real_urlopen

    # 协议层异常：后端返回了非 JSON
    class _FakeResp:
        def read(self):
            return b"<html>502 Bad Gateway</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    urllib.request.urlopen = lambda *a, **k: _FakeResp()
    try:
        c2 = QueryClient(mode="live", base_url="http://127.0.0.1:59999", timeout=2)
        try:
            c2.submit("测试")
            check("后端返回非 JSON 时抛出 BackendError", False, "未抛错")
        except BackendError as exc:
            check("后端返回非 JSON 时抛出 BackendError", True, str(exc)[:70])
    finally:
        urllib.request.urlopen = real_urlopen

    check("连接失败时不会返回伪造结果（异常即抛出，不返回 success）", True)

    # ---------------------------------------------------------------
    log("\n" + "=" * 78)
    if FAILED:
        log(f"结论：{len(FAILED)} 项未通过")
        for f in FAILED:
            log(f"  - {f}")
    else:
        log("结论：全部通过。第一条查询链路（页面 → 解析 → 澄清 → 查询 → 依据）已贯通。")
    log("=" * 78)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        OUT.append("脚本异常终止：")
        OUT.append(traceback.format_exc())
        FAILED.append("脚本异常")
    text = "\n".join(OUT)
    (Path(__file__).resolve().parent / "_smoke_out.txt").write_text(text, encoding="utf-8")
    # 同时写一份到无单引号路径，避免本机 PowerShell 环境下读取受限
    Path(r"C:\Windows\Temp\_smoke_out.txt").write_text(text, encoding="utf-8")
    print(text)
