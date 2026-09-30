# -*- coding: utf-8 -*-
"""测试集自动评分器（成员 3 主责，分工文档 §5.2.3）。

做的事：
1. 读取开发集或保留集的 30 道题，逐条真实调用平台；
2. 按「预期状态 + 预期指标 / 时间 / 分组」自动判定，不需要人工逐题看；
3. 输出 per-question 结果 CSV + 汇总指标，汇总指标可直接填进对照实验记录表。

判定优先级里最高的一档是「编造」：数据不足或超出范围时仍给出确定结论，
这是分工文档 §4.4 明确禁止的行为，必须单独统计、单独归类。

标准答案（数值）由成员 1 计算并填写原 CSV 的「标准答案」列后再复核；
本脚本负责的是**状态与元数据**层面的自动判定。

用法：
    python tests/run_testset.py 开发集
    python tests/run_testset.py 保留集
"""

from __future__ import annotations

import csv
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)

import mock_backend  # noqa: E402
from demo_data import demo_tables  # noqa: E402
from shared.contracts import Status  # noqa: E402

OUT = [r"C:\Windows\Temp\_testset_out.txt", ROOT / "tests" / "_testset_out.txt"]
LINES = []
PLACEHOLDER = {"待澄清", "待定", "不适用", "待成员1计算", ""}

SETS = {
    # 开发集 = 30 道正式题 + 7 道补充回归题。
    # 补充回归题的来源：保留集首轮基线暴露的失败类型，按方法论要求
    # **回写到开发集**来修实现，而不是拿保留集调参（否则保留集会失效）。
    "开发集": [ROOT / "tests" / "测试题_开发集_30题.csv",
             ROOT / "tests" / "测试题_开发集_补充回归7题.csv"],
    "保留集": [ROOT / "tests" / "测试题_保留集_30题.csv"],
}


def log(msg: str = "") -> None:
    LINES.append(str(msg))
    for p in OUT:
        try:
            Path(p).write_text("\n".join(LINES), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


def split_options(raw: str) -> list:
    return [s.strip() for s in re.split(r"[或/、]", str(raw or "")) if s.strip()]


def brief(resp: dict) -> str:
    st = resp.get("status")
    if st == Status.SUCCESS:
        row = (resp.get("data") or [{}])[0]
        return "; ".join(f"{k}={v}" for k, v in row.items())
    if st == Status.NEED_CLARIFICATION:
        clr = resp.get("clarification") or {}
        return f"{clr.get('question', '')[:40]} | 候选={[o['value'] for o in clr.get('options', [])]}"
    return f"reason={resp.get('reason')}"


def judge(row: dict, resp: dict) -> tuple:
    """返回 (判定, 错误分类, 备注)。"""
    actual = resp.get("status")
    expected_opts = split_options(row.get("预期状态"))

    # ---- 状态不一致：先按「是否编造」归类，这是最严重的一档 ----
    if actual not in expected_opts:
        expects_refuse = set(expected_opts) & {Status.INSUFFICIENT_DATA, Status.OUT_OF_SCOPE}
        if actual == Status.SUCCESS and expects_refuse:
            return "错误", "编造（该拒答却给出确定结论）", "数据不支持时仍返回了数值"
        if actual == Status.SUCCESS and Status.NEED_CLARIFICATION in expected_opts:
            return "错误", "该澄清未澄清", "未经澄清直接使用了默认口径"
        if actual == Status.NEED_CLARIFICATION and Status.SUCCESS in expected_opts:
            return "错误", "不该澄清却追问", "问题已明确但仍在追问"
        if actual in (Status.EXECUTION_FAILED, Status.MODEL_OUTPUT_INVALID):
            return "错误", "执行失败", resp.get("message", "")
        return "错误", "状态不符", f"预期 {expected_opts} / 实际 {actual}"

    # ---- 状态一致，做附加校验 ----
    if actual == Status.SUCCESS:
        exp_metric = row.get("预期指标", "").strip()
        if exp_metric not in PLACEHOLDER:
            opts = split_options(exp_metric)
            if resp.get("metric") not in opts:
                return "错误", "指标识别错误", f"预期 {opts} / 实际 {resp.get('metric')}"
        exp_range = row.get("预期时间范围", "").strip()
        if exp_range not in PLACEHOLDER and "~" in exp_range:
            want = exp_range.split("~")
            got = [resp.get("date_start"), resp.get("date_end")]
            if list(want) != list(got):
                return "错误", "时间解析错误", f"预期 {want} / 实际 {got}"
        exp_group = row.get("预期分组", "").strip()
        if exp_group not in PLACEHOLDER:
            got_all = ["不分组"] if not resp.get("group_by") else list(resp["group_by"])
            if exp_group not in got_all:
                return "错误", "分组错误", f"预期 {exp_group} / 实际 {got_all}"
        return "正确", "", ""

    if actual == Status.NEED_CLARIFICATION:
        clr = resp.get("clarification") or {}
        if not clr.get("options"):
            return "部分正确", "澄清不合理", "未提供候选口径"
        if not clr.get("id", "").startswith("clr_"):
            return "部分正确", "澄清 id 不符合约定", str(clr.get("id"))
        return "正确", "", f"候选={[o['value'] for o in clr['options']]}"

    # insufficient_data / out_of_scope
    if not resp.get("reason"):
        return "部分正确", "缺少原因码", ""
    if not resp.get("suggestion"):
        return "部分正确", "缺少下一步建议", ""
    if actual == Status.INSUFFICIENT_DATA and not resp.get("missing"):
        return "部分正确", "未列出缺少的信息", "契约要求 missing 必须具体"
    return "正确", "", ""


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "开发集"
    srcs = SETS.get(which)
    if srcs is None or not any(p.exists() for p in srcs):
        log(f"未找到测试集：{which}")
        return

    log("=" * 78)
    log(f"数桥 DataBridge · {which}自动评分")
    log("=" * 78)

    t0 = time.time()
    tables = demo_tables()
    log(f"\n数据：orders {len(tables['orders']):,} 行 / "
        f"refunds {len(tables['refunds']):,} 行 / customers {len(tables['customers']):,} 行")
    log(f"生成耗时 {time.time() - t0:.2f}s\n")

    rows = []
    for src in srcs:
        if not src.exists():
            continue
        with open(src, encoding="utf-8-sig", newline="") as fh:
            rows.extend(csv.DictReader(fh))

    results = []
    for row in rows:
        resp = mock_backend.handle(row["问题"], tables=tables)
        verdict, err_type, note = judge(row, resp)
        results.append({
            "题号": row["题号"],
            "问题": row["问题"],
            "分类": row["分类"],
            "预期状态": row["预期状态"],
            "实际状态": resp.get("status"),
            "判定": verdict,
            "错误分类": err_type,
            "实际指标": resp.get("metric", ""),
            "实际时间范围": f"{resp.get('date_start', '')}~{resp.get('date_end', '')}"
                            if resp.get("date_start") else "",
            "实际分组": "、".join(resp.get("group_by") or []) or "不分组",
            "实际返回": brief(resp),
            "备注": note,
        })

    log(f"{'题号':<6}{'预期状态':<22}{'实际状态':<22}{'判定':<8}错误分类")
    log("-" * 100)
    for r in results:
        log(f"{r['题号']:<6}{r['预期状态']:<22}{r['实际状态']:<22}{r['判定']:<8}{r['错误分类']}")

    # ---- 汇总 ----
    total = len(results)
    ok = sum(1 for r in results if r["判定"] == "正确")
    partial = sum(1 for r in results if r["判定"] == "部分正确")
    bad = sum(1 for r in results if r["判定"] == "错误")
    clarify_ok = sum(1 for r in results
                     if r["实际状态"] == Status.NEED_CLARIFICATION and r["判定"] == "正确")
    fabricated = sum(1 for r in results if "编造" in r["错误分类"])

    log("\n" + "=" * 78)
    log("汇总（可直接填入对照实验记录表）")
    log("=" * 78)
    log(f"  总题数            {total}")
    log(f"  正确回答数量      {ok}")
    log(f"  部分正确          {partial}")
    log(f"  错误回答数量      {bad}")
    log(f"  正确澄清数量      {clarify_ok}")
    log(f"  无依据编造数量    {fabricated}")
    log(f"  任务完成率        {(ok + partial / 2) / total:.1%}（部分正确按 0.5 计）")

    if bad + partial:
        log("\n需要复核的题目：")
        for r in results:
            if r["判定"] != "正确":
                log(f"  {r['题号']} [{r['判定']}] {r['分类']}｜{r['问题']}")
                log(f"        预期={r['预期状态']} 实际={r['实际状态']} "
                    f"→ {r['错误分类']}｜{r['备注']}｜返回：{r['实际返回']}")

    # 写回结果 CSV
    dst = ROOT / "tests" / f"_评测结果_{which}.csv"
    with open(dst, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    log(f"\n明细已写入：{dst}")

    log("\n" + "=" * 78)
    log("说明：本结果为「页面侧参考实现」的基线，不是最终产品的成绩。"
        "成员 2 的 AI 流程接入后需要重跑并对比。"
        if (bad + partial) else "说明：全部通过。")
    log("=" * 78)


if __name__ == "__main__":
    main()
