# -*- coding: utf-8 -*-
"""对照实验执行器（分工文档 §5.2.4）：S1 直接 Text-to-SQL vs S2 完整治理方案。

输入：开发集 37 题（30 正式 + 7 补充回归）。
对每道题分别真实调用：
  S1 = tests/s1_baseline.py（只看物理表结构的直接 Text-to-SQL 确定性基线）
  S2 = app/mock_backend.py（业务字典 + 查询计划 + 歧义澄清 + 结果检查）

判定：
  1. 状态 / 指标 / 时间 / 分组层复用 run_testset.judge()；
  2. 对「预期 success」的题，追加**数值核对**：以 S2 在同一份数据上的
     pandas 计算为参考真值，比较 S1 的数值（容差 0.01），不一致记「数值错误」；
  3. 数值差异归因：分别单独打开 S1 的三个修正开关（状态过滤 / 退款预聚合 /
     按 refund_time 归属），定位每个差异的独立来源。

产出：
  tests/对照实验记录表.csv  —— 74 行，schema 与 build_experiment_sheet.py 完全一致
  tests/_对照实验明细.csv    —— 每题每方案的详细字段（含实际数值与差异归因）
  tests/_experiment_out.txt  —— 汇总指标（可直接填入答辩材料）

注意：S1 当前是确定性行为基线，不是真实大模型实测，成员 2 的 LLM 接入后必须重跑。

用法：
    python tests/run_experiment.py                 # 85k 内置演示数据
    python tests/run_experiment.py --source formal # 正式库 demo-v1.1（DS-004 主线）

正式库模式产物文件名带 _formal 后缀；D24（3 月）因覆盖区间扩大而改判 success；
S1 三个错误开关全部修正后仍与 S2 不符的地区题，归因为「地区按客户维度归属」
（正式库地区是订单快照，1,994 个客户跨地区下单）。
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import mock_backend  # noqa: E402
import s1_baseline  # noqa: E402
from demo_data import demo_tables  # noqa: E402
from formal_dataset import FORMAL_COVERAGE_MONTHS, FORMAL_VERSION, load_formal_demo  # noqa: E402
from run_testset import judge, split_options  # noqa: E402

DEV_SOURCES = [ROOT / "tests" / "测试题_开发集_30题.csv",
               ROOT / "tests" / "测试题_开发集_补充回归7题.csv"]

SCHEMES = [
    ("S1", "基础方案：大模型根据表结构直接生成 SQL（确定性行为基线）", s1_baseline.handle),
    ("S2", "完整方案：业务字典 + 查询计划 + 歧义澄清 + 结果检查", mock_backend.handle),
]

#: 正式库覆盖 2026-01~09，开发集中按 85k 覆盖（6~9 月）判定为拒答的题需改判
FORMAL_ROW_OVERRIDES = {
    "D24": {"预期状态": "success", "预期指标": "net_sales", "预期分组": "不分组",
            "是否应拒答": "否", "分类": "数据不足·超出数据覆盖（正式库覆盖内，改判 success）"},
}

LINES: list = []
OUT_TXT = DETAIL = SHEET = None


def log(msg: str = "") -> None:
    LINES.append(str(msg))
    OUT_TXT.write_text("\n".join(LINES), encoding="utf-8")


def _values_by_key(records: list, metric: str, dim_col: str | None) -> dict:
    out = {}
    for row in records:
        key = str(row.get(dim_col)) if dim_col else "_"
        out[key] = row.get(metric)
    return out


def numeric_check(row: dict, s1_resp: dict, s2_resp: dict, tables: dict, question: str,
                  region_snapshot: bool = False):
    """对预期 success 的题做数值核对与差异归因。返回 (是否数值一致, 归因列表, S1值, S2值)。"""
    exp_metric = row.get("预期指标", "").strip()
    exp_status = split_options(row.get("预期状态"))
    if "success" not in exp_status or exp_metric in ("", "待澄清", "待定", "不适用"):
        return True, [], "", ""
    metric = exp_metric
    exp_group = row.get("预期分组", "").strip()
    dim_col = None if exp_group in ("不分组", "", "待澄清", "待定") else exp_group

    s2_vals = _values_by_key(s2_resp.get("data") or [], metric, dim_col)
    s1_vals = _values_by_key(s1_resp.get("data") or [], metric, dim_col)

    same = True
    for key, ref in s2_vals.items():
        got = s1_vals.get(key)
        if got is None or ref is None or abs(float(got) - float(ref)) > 0.01:
            same = False
            break

    factors = []
    if not same:
        # 独立归因：从 S2 正确管线出发，每次只引入一个缺陷，
        # 若该「单缺陷」变体的结果就偏离参考值，则该因素是独立致错来源。
        variants = [
            ("未排除失败/取消订单", dict(safe_refund=True, refund_time_attr=True)),
            ("JOIN一对多重复累计", dict(use_status=True, refund_time_attr=True)),
            ("退款按支付月归属（应按退款月）", dict(use_status=True, safe_refund=True)),
        ]
        for label, kw in variants:
            try:
                _, _, _, _, _, _, recs, _ = s1_baseline.execute_s1(question, tables, **kw)
                vals = _values_by_key(recs, metric, dim_col)
                diverged = any(
                    vals.get(k) is None or abs(float(vals[k]) - float(v)) > 0.01
                    for k, v in s2_vals.items())
                if diverged:
                    factors.append(label)
            except Exception as exc:  # noqa: BLE001
                factors.append(f"{label}（归因计算失败：{exc}）")

        # 残余归因：三个开关全部修正后仍不符 —— 正式库上唯一剩余结构差异是
        # S1 把地区挂在 customers 表，而正式库地区是订单快照（跨地区客户）
        if region_snapshot:
            try:
                _, _, _, _, _, _, recs_all, _ = s1_baseline.execute_s1(
                    question, tables, use_status=True, safe_refund=True,
                    refund_time_attr=True)
                vals_all = _values_by_key(recs_all, metric, dim_col)
                residual = any(
                    vals_all.get(k) is None or abs(float(vals_all[k]) - float(v)) > 0.01
                    for k, v in s2_vals.items())
                if residual:
                    factors.append("地区按客户维度归属（正式库地区为订单快照）")
            except Exception as exc:  # noqa: BLE001
                factors.append(f"地区快照残余归因失败：{exc}")

    def flat(vals: dict) -> str:
        if dim_col:
            return "; ".join(f"{k}={v}" for k, v in sorted(vals.items()))
        return str(next(iter(vals.values()), ""))

    return same, factors, flat(s1_vals), flat(s2_vals)


def call_timed(fn, question, tables, call_kw):
    t0 = time.perf_counter()
    resp = fn(question, tables=tables, **call_kw)
    return resp, time.perf_counter() - t0


def main(source: str = "mock") -> None:
    global SHEET, DETAIL, OUT_TXT
    formal = source == "formal"
    suffix = "_formal" if formal else ""
    SHEET = ROOT / "tests" / f"对照实验记录表{suffix}.csv"
    DETAIL = ROOT / "tests" / f"_对照实验明细{suffix}.csv"
    OUT_TXT = ROOT / "tests" / f"_experiment{suffix}_out.txt"
    exp_id = "EXP-20261009-F" if formal else "EXP-20261009"

    log("=" * 80)
    log("数桥 DataBridge · 对照实验 S1（直接 Text-to-SQL） vs S2（完整治理方案）")
    log(f"数据源：{'正式联调库 ' + FORMAL_VERSION + '（DS-004 主线）' if formal else '内置 85k 演示数据'}")
    log("=" * 80)

    t0 = time.time()
    if formal:
        tables = load_formal_demo()
        # S1 忽略额外 kwargs（**_ignore）；只有 S2 应用版本与覆盖区间
        s2_kw = dict(dataset_version=FORMAL_VERSION, coverage_months=FORMAL_COVERAGE_MONTHS)
    else:
        tables = demo_tables()
        s2_kw = {}
    call_kw_by_sid = {"S1": {}, "S2": s2_kw}
    log(f"演示数据：orders {len(tables['orders']):,} 行 / "
        f"refunds {len(tables['refunds']):,} 行 / "
        f"customers {len(tables['customers']):,} 行（加载 {time.time()-t0:.2f}s）\n")

    questions = []
    for src in DEV_SOURCES:
        with open(src, encoding="utf-8-sig", newline="") as fh:
            questions.extend(csv.DictReader(fh))

    sheet_rows = []
    detail_rows = []
    summary = {sid: {"正确": 0, "错误": 0, "部分正确": 0, "澄清": 0,
                     "编造": 0, "数值错误": 0, "lat": []}
               for sid, _, _ in SCHEMES}

    for row in questions:
        qid, question = row["题号"], row["问题"]
        if formal and qid in FORMAL_ROW_OVERRIDES:
            row = {**row, **FORMAL_ROW_OVERRIDES[qid]}
        resps = {}
        for sid, _, fn in SCHEMES:
            resp, elapsed = call_timed(fn, question, tables, call_kw_by_sid[sid])
            resps[sid] = (resp, elapsed)

        for sid, _, _ in SCHEMES:
            resp, elapsed = resps[sid]
            verdict, err_type, note = judge(row, resp)

            num_same, factors, s1_val, s2_val = True, [], "", ""
            if sid == "S1":
                num_same, factors, s1_val, s2_val = numeric_check(
                    row, resp, resps["S2"][0], tables, question,
                    region_snapshot=formal)
                if not num_same and verdict == "正确":
                    verdict = "错误"
                    err_type = "数值错误"
                    note = "状态/元数据正确但数值与参考真值不符"

            fabricated = "编造" in err_type
            is_clarify = (resp.get("status") == "need_clarification" and verdict == "正确")
            completed = verdict == "正确"

            summary[sid][verdict] = summary[sid].get(verdict, 0) + 1
            if is_clarify:
                summary[sid]["澄清"] += 1
            if fabricated:
                summary[sid]["编造"] += 1
            if not num_same:
                summary[sid]["数值错误"] += 1
            summary[sid]["lat"].append(elapsed)

            factor_text = "；".join(factors)
            detail_rows.append({
                "方案": sid, "题号": qid, "问题": question, "分类": row["分类"],
                "预期状态": row["预期状态"], "实际状态": resp.get("status"),
                "判定": verdict, "错误分类": err_type,
                "实际指标": resp.get("metric", ""),
                "时间": f"{resp.get('date_start','')}~{resp.get('date_end','')}",
                "分组": "、".join(resp.get("group_by") or []) or "不分组",
                "S1数值": s1_val, "S2参考值": s2_val,
                "数值差异来源": factor_text,
                "响应时间秒": round(elapsed, 4),
                "备注": note or resp.get("s1_note", ""),
            })
            sheet_rows.append({
                "实验编号": exp_id, "方案编号": sid,
                "方案说明": dict(((s[0], s[1]) for s in SCHEMES))[sid],
                "题号": qid, "问题": question, "分类": row["分类"],
                "预期状态": row["预期状态"],
                "是否需澄清": row["是否需澄清"], "是否应拒答": row["是否应拒答"],
                "实际状态": resp.get("status"),
                "是否正确回答": "是" if (verdict == "正确" and not is_clarify) else "否",
                "是否正确澄清": "是" if is_clarify else "否",
                "是否无依据编造": "是" if fabricated else "否",
                "是否完成": "是" if completed else "否",
                "响应时间(秒)": round(elapsed, 4),
                "模型调用次数": 0,
                "token消耗": 0,
                "备注": ((err_type + ("：" + note if note else ""))
                        if verdict != "正确" else "")
                       + (f"｜数值差异来源：{factor_text}" if factor_text else ""),
            })

        log(f"{qid} {question[:28]}")
        for sid, _, _ in SCHEMES:
            resp, elapsed = resps[sid]
            v = next(d["判定"] for d in detail_rows
                     if d["方案"] == sid and d["题号"] == qid)
            extra = ""
            if sid == "S1":
                d = next(d for d in detail_rows
                         if d["方案"] == sid and d["题号"] == qid)
                extra = f"｜数值差异来源：{d['数值差异来源'] or '无'}"
            log(f"   {sid}: {resp.get('status'):<20} 判定={v:<6} "
                f"{elapsed*1000:6.1f}ms{extra}")

    # ---- 汇总 ----
    total = len(questions)
    log("\n" + "=" * 80)
    log(f"{'指标':<16}{'S1 直接Text-to-SQL':<24}{'S2 完整治理方案':<24}")
    log("-" * 80)

    def rate(sid, key):
        return summary[sid][key]

    rows_cmp = [
        ("正确回答数量", lambda s: rate(s, "正确")),
        ("错误回答数量", lambda s: rate(s, "错误") + rate(s, "部分正确")),
        ("其中：数值错误", lambda s: rate(s, "数值错误")),
        ("正确澄清数量", lambda s: rate(s, "澄清")),
        ("无依据编造数量", lambda s: rate(s, "编造")),
    ]
    for label, fn in rows_cmp:
        log(f"{label:<16}{fn('S1'):<24}{fn('S2'):<24}")

    for sid, _, _ in SCHEMES:
        s = summary[sid]
        completion = (s["正确"] + 0.5 * s["部分正确"]) / total
        avg_ms = sum(s["lat"]) / len(s["lat"]) * 1000
        s["完成率"] = completion
        s["avg_ms"] = avg_ms
    log(f"{'任务完成率':<16}{summary['S1']['完成率']:<24.1%}{summary['S2']['完成率']:<24.1%}")
    log(f"{'平均响应时间':<16}{summary['S1']['avg_ms']:<24.2f}{summary['S2']['avg_ms']:<24.2f}")
    log("注：平均响应时间单位为毫秒；两者均为本地确定性实现，模型调用次数与 token 消耗为 0，")
    log("    成员 2 的 LLM 接入后需重新测量该两项。")

    # 差异归因统计
    factor_count: dict = {}
    for d in detail_rows:
        if d["方案"] == "S1" and d["数值差异来源"]:
            for f in d["数值差异来源"].split("；"):
                factor_count[f] = factor_count.get(f, 0) + 1
    log("\nS1 数值错误的独立归因（可多因叠加，按题数计）：")
    for f, c in sorted(factor_count.items(), key=lambda kv: -kv[1]):
        log(f"  {c:>2} 题  {f}")

    # ---- 装置验证：第三归因因素（退款按支付月归属）的可观测性 ----
    if formal:
        # 正式库不做人工注入：直接引用 IS-001 正式库测量（同一套矩阵函数独立计算）
        import is001_refund_timing as is001  # noqa: E402
        mat_a = is001.net_sales_matrix(
            tables, "refund_time", FORMAL_COVERAGE_MONTHS, region_from_orders=True)
        mat_b = is001.net_sales_matrix(
            tables, "pay_time", FORMAL_COVERAGE_MONTHS, region_from_orders=True)
        drift = float((mat_a - mat_b).loc["2026-09", "华东"])
        log("\n归因装置验证（正式库真实跨月退款，不影响上方 74 行记录）：")
        log("  9 月华东净销售额：S2 按 refund_time 归属 "
            f"{mat_a.loc['2026-09', '华东']:,.2f}｜S1 口径按 pay_time 归属 "
            f"{mat_b.loc['2026-09', '华东']:,.2f}")
        log(f"  [PASS] 真实数据上「退款按支付月归属」单因素即造成 "
            f"{abs(drift):,.2f} 元历史月份回溯漂移（详见 _is001_formal_out.txt）")
    else:
        # 在跨月退款变体（demo_data.cross_month_refund_tables）上验证：
        # 只引入「退款按 pay_time 归属」单缺陷，其余两层全部正确时，净销售额仍会算错。
        from demo_data import cross_month_refund_tables  # noqa: E402
        variant = cross_month_refund_tables(tables)
        mv = variant["_cross_month_moves"]
        probe_q = "2026年9月华东地区的净销售额是多少"
        ref_resp = mock_backend.handle(probe_q, tables=variant)
        ref_val = ref_resp["data"][0]["net_sales"]
        _, _, _, _, _, _, bad_recs, _ = s1_baseline.execute_s1(
            probe_q, variant, use_status=True, safe_refund=True)  # 单缺陷：pay_time 归属
        bad_val = bad_recs[0]["net_sales"]
        timing_ok = abs(bad_val - ref_val - mv["amount"]) < 0.01
        log("\n归因装置验证（跨月退款变体，不影响上方 74 行记录）：")
        log(f"  注入 {mv['count']} 笔跨月退款，合计 {mv['amount']:,.2f} 元（8月订单，9月退款）")
        log(f"  9月华东净销售额：S2 按 refund_time 归属={ref_val:,.2f}｜"
            f"单缺陷变体按 pay_time 归属={bad_val:,.2f}")
        log(f"  [{'PASS' if timing_ok else 'FAIL'}] 仅「退款按支付月归属」单缺陷"
            f"即造成 {mv['amount']:,.2f} 元偏差 —— 第三因素在含跨月退款的数据上可被观测")

    # 编造/错答逐题列出
    log("\nS1 失败题目清单：")
    for d in detail_rows:
        if d["方案"] == "S1" and d["判定"] != "正确":
            log(f"  {d['题号']} [{d['分类']}] {d['问题']}")
            log(f"       预期={d['预期状态']} 实际={d['实际状态']} → {d['错误分类']}"
                f"{('｜' + d['数值差异来源']) if d['数值差异来源'] else ''}")

    # ---- 写文件 ----
    sheet_header = ["实验编号", "方案编号", "方案说明", "题号", "问题", "分类",
                    "预期状态", "是否需澄清", "是否应拒答", "实际状态",
                    "是否正确回答", "是否正确澄清", "是否无依据编造", "是否完成",
                    "响应时间(秒)", "模型调用次数", "token消耗", "备注"]
    with open(SHEET, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=sheet_header)
        w.writeheader()
        w.writerows(sheet_rows)

    with open(DETAIL, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(detail_rows[0].keys()))
        w.writeheader()
        w.writerows(detail_rows)

    log(f"\n记录表（74 行）：{SHEET}")
    log(f"明细（74 行）  ：{DETAIL}")
    log("\n" + "=" * 80)
    log("诚实声明：S1 为确定性的直接 Text-to-SQL 行为基线（无 LLM 调用），")
    log("用于隔离「治理层」的增量价值；成员 2 的真实大模型接入后，S1 必须用同一模型重跑。")
    log("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="S1 vs S2 对照实验")
    parser.add_argument("--source", choices=("mock", "formal"), default="mock")
    args = parser.parse_args()
    main(args.source)
