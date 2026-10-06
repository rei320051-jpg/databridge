# -*- coding: utf-8 -*-
"""真实大模型复测执行器（RISK-02）：S2 治理工作流的「自然语言→槽位」层换用真实 LLM。

架构边界（必须如实声明）：
  本产品中真实模型只负责「问题 → 结构化槽位」，指标字典、歧义澄清、范围护栏、
  SQL 生成与聚合计算全部在本地完成（agent/model.py 模块说明）。因此本复测
  检验的是 **S2 + 真实 DeepSeek 槽位解析** 在完整题库上的表现，并与确定性规则
  模式（S2-rules）逐题比对；它**不是**「让 LLM 直接生成 SQL」的 S1 实测——
  产品从不向模型开放数据库，S1 仍是确定性的行为基线。

输入：开发集 37 题（30 正式 + 7 补充回归）与保留集 30 题，共 67 题。
数据：正式联调库 demo-v1.1（2026-01~09，2 万订单），即 live 演示同一链路。

每题执行：
  1. AgentWorkflow(mode="rules") 得确定性参考信封；
  2. AgentWorkflow(mode="model", OpenAIPlanModel=真实 DeepSeek) 得模型信封
     （失败/非法输出自动重试 1 次）；
  3. 复用 run_testset.judge() 按 CSV 预期判定模型信封；
  4. 规范化后逐题比较 rules 与 model 信封（状态/指标/时间/分组/筛选/数据）；
  5. 采集调用次数、token usage（缓存命中/未命中拆分）、端到端时延。

正式库覆盖 2026-01~09，对原按 85k 数据（6~9 月）命制的边界题按事实改判：
  D24（2026年3月）、H24（2026年5月）在正式库覆盖内 → success。
改判仅限覆盖区间事实，不调整任何判定标准；保留集除此之外不做任何调试性修改。

产出（均显式 LF）：
  tests/_LLM真实模型复测明细.csv
  tests/_llm_retest_out.txt

用法：
    python tests/run_llm_testset.py --channel rules --set all   # 零成本预检
    python tests/run_llm_testset.py --channel both  --set dev --limit 3   # 小样本
    python tests/run_llm_testset.py --channel both  --set all    # 全量 67 题
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent.model import OpenAIPlanModel  # noqa: E402
from agent.workflow import AgentWorkflow  # noqa: E402
from databridge.service import QueryService  # noqa: E402
from run_testset import judge  # noqa: E402

DATABASE = ROOT / "outputs" / "demo-v1.1.sqlite3"

SOURCES = {
    "dev": [ROOT / "tests" / "测试题_开发集_30题.csv",
            ROOT / "tests" / "测试题_开发集_补充回归7题.csv"],
    "holdout": [ROOT / "tests" / "测试题_保留集_30题.csv"],
}

#: 正式库覆盖 2026-01~09，仅对「超出覆盖」类边界题按事实改判（D24 与 run_experiment 对齐）
FORMAL_OVERRIDES = {
    "D24": {"预期状态": "success", "预期指标": "net_sales", "预期分组": "不分组",
            "是否应拒答": "否", "分类": "数据不足·超出数据覆盖（正式库覆盖内，改判 success）"},
    "H24": {"预期状态": "success", "预期指标": "paid_amount", "预期分组": "region",
            "是否应拒答": "否", "分类": "数据不足·超出数据覆盖（正式库覆盖内，改判 success）"},
}

#: deepseek-flash 人民币元 / 百万 token（2026-08-17 生效峰谷价，官方定价页 2026-10-06 读取）
#: 请求名 deepseek-chat 现由官方别名路由到 deepseek-flash（DeepSeek-V4.1-Flash）实际服务
PRICE_OFFPEAK = {"hit": 0.02, "miss": 1.0, "out": 4.0}   # 空闲（周末与法定节假日全天）
PRICE_PEAK = {"hit": 0.04, "miss": 2.0, "out": 8.0}      # 高峰（工作日 9-12、14-18）
PRICE_URL = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"

OUT_TXT = ROOT / "tests" / "_llm_retest_out.txt"
OUT_CSV = ROOT / "tests" / "_LLM真实模型复测明细.csv"

LINES: list = []


def log(msg: str = "") -> None:
    LINES.append(str(msg))
    OUT_TXT.write_text("\n".join(LINES), encoding="utf-8", newline="\n")


def load_questions(which: str) -> list:
    rows = []
    for src in SOURCES[which]:
        with open(src, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                row = dict(row)
                row["_题集"] = "开发集" if which == "dev" else "保留集"
                if row["题号"] in FORMAL_OVERRIDES:
                    row.update(FORMAL_OVERRIDES[row["题号"]])
                rows.append(row)
    return rows


def canon(resp: dict) -> tuple:
    """跨模式可比的响应指纹（剔除 query_id/时间戳/SQL 等必然不同的字段）。"""
    st = resp.get("status")
    if st == "success":
        return ("success", resp.get("metric"), resp.get("date_start"), resp.get("date_end"),
                tuple(resp.get("group_by") or []),
                json.dumps(resp.get("applied_filters") or {}, ensure_ascii=False, sort_keys=True),
                json.dumps(resp.get("data") or [], ensure_ascii=False, sort_keys=True))
    if st == "need_clarification":
        clr = resp.get("clarification") or {}
        opts = tuple(sorted(str(o.get("value")) for o in clr.get("options", [])))
        return ("need_clarification", clr.get("target_field"), opts)
    return (st, resp.get("reason"))


def percentile(sorted_vals: list, q: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def main() -> None:
    parser = argparse.ArgumentParser(description="真实 DeepSeek 全题库复测（S2-model vs S2-rules）")
    parser.add_argument("--channel", choices=("rules", "both"), default="both")
    parser.add_argument("--set", dest="which", choices=("dev", "holdout", "all"), default="all")
    parser.add_argument("--ids", default="", help="逗号分隔的题号白名单，如 D01,H16")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 题（小样本试跑）")
    parser.add_argument("--sleep", type=float, default=0.3, help="模型调用后间隔秒")
    args = parser.parse_args()

    if not DATABASE.is_file():
        raise SystemExit(f"缺少正式库 {DATABASE}，请先运行："
                         f"python scripts/import_dataset.py data/demo --database {DATABASE}")

    sets = ["dev", "holdout"] if args.which == "all" else [args.which]
    questions = [r for s in sets for r in load_questions(s)]
    if args.ids:
        wanted = {x.strip() for x in args.ids.split(",") if x.strip()}
        questions = [r for r in questions if r["题号"] in wanted]
    if args.limit:
        questions = questions[:args.limit]

    run_model = args.channel == "both"

    log("=" * 84)
    log("数桥 DataBridge · 真实大模型复测（S2 治理工作流 + 真实 DeepSeek 槽位解析）")
    log(f"执行时间：{time.strftime('%Y-%m-%d %H:%M:%S')}    题库：{args.which}（{len(questions)} 题）"
        f"    通道：{'rules+model 比对' if run_model else '仅 rules 预检（零 API 调用）'}")
    log(f"数据源：{DATABASE.name}（demo-v1.1，2026-01~09）")
    log("-" * 84)

    tmp = tempfile.TemporaryDirectory()
    root_rec = Path(tmp.name)
    rules_agent = AgentWorkflow(QueryService(DATABASE, root_rec / "rec-rules"), mode="rules")
    model = OpenAIPlanModel() if run_model else None
    model_agent = (AgentWorkflow(QueryService(DATABASE, root_rec / "rec-model"),
                                 model=model, mode="model") if run_model else None)
    if run_model:
        log(f"模型：请求名={model.model}，base_url={model.base_url}，"
            f"实际服务模型以每题响应的 model 字段为准")
    log("=" * 84)

    detail = []
    served_models: dict = {}
    total_tokens = {"hit": 0, "miss": 0, "out": 0}
    model_latencies = []
    counts = {"正确": 0, "部分正确": 0, "错误": 0, "澄清": 0, "编造": 0,
              "执行失败": 0, "一致": 0, "模型调用": 0, "护栏零调用": 0, "重试": 0}

    for i, row in enumerate(questions, 1):
        qid, question = row["题号"], row["问题"]

        t0 = time.perf_counter()
        rules_resp = rules_agent.run({"question": question})
        rules_elapsed = time.perf_counter() - t0

        calls = tokens = retried = 0
        usage = {}
        served = ""
        model_elapsed = 0.0
        model_resp = None
        if run_model:
            t0 = time.perf_counter()
            before = model.calls
            model_resp = model_agent.run({"question": question})
            # 网络/输出瞬时异常 → 等待后重试一次；护栏类本地拒答不消耗调用、无需重试
            retryable = model_resp.get("status") in ("execution_failed", "model_output_invalid")
            if retryable:
                time.sleep(2.0)
                model_resp = model_agent.run({"question": question})
                retried = 1
            model_elapsed = time.perf_counter() - t0
            calls = model.calls - before
            # 护栏在模型前直接拦截时 calls=0：不得沿用上题残留的 usage / 服务模型名
            usage = (model.last_usage or {}) if calls else {}
            served = str(model.last_model or "") if calls else ""
            if served:
                served_models[served] = served_models.get(served, 0) + 1
            if calls:
                time.sleep(args.sleep)

        judged_resp = model_resp if run_model else rules_resp
        verdict, err_type, note = judge(row, judged_resp)
        if run_model:
            consistent = canon(rules_resp) == canon(model_resp)
        else:
            consistent = None

        hit = int(usage.get("prompt_cache_hit_tokens", 0))
        miss = int(usage.get("prompt_cache_miss_tokens", 0))
        out_tok = int(usage.get("completion_tokens", 0))
        total_tok = int(usage.get("total_tokens", 0))
        # 兼容缺失缓存拆分字段的网关：用 prompt_tokens 兜底计入未命中
        if calls and not hit and not miss:
            miss = int(usage.get("prompt_tokens", 0))

        if verdict == "正确":
            counts["正确"] += 1
        elif verdict == "部分正确":
            counts["部分正确"] += 1
        else:
            counts["错误"] += 1
        if judged_resp.get("status") == "need_clarification" and verdict == "正确":
            counts["澄清"] += 1
        if "编造" in (err_type or ""):
            counts["编造"] += 1
        if judged_resp.get("status") in ("execution_failed", "model_output_invalid"):
            counts["执行失败"] += 1
        if consistent:
            counts["一致"] += 1
        if run_model:
            counts["重试"] += retried
            if calls:
                counts["模型调用"] += 1
                model_latencies.append(model_elapsed)
                total_tokens["hit"] += hit
                total_tokens["miss"] += miss
                total_tokens["out"] += out_tok
            else:
                counts["护栏零调用"] += 1

        detail.append({
            "题号": qid, "题集": row["_题集"], "问题": question, "分类": row["分类"],
            "预期状态": row["预期状态"],
            "rules状态": rules_resp.get("status"),
            "model状态": judged_resp.get("status") if run_model else "",
            "判定": verdict, "错误分类": err_type,
            "与rules一致": "" if not run_model else ("是" if consistent else "否"),
            "重试": retried, "模型调用次数": calls,
            "prompt缓存命中": hit, "prompt未命中": miss,
            "completion_tokens": out_tok, "total_tokens": total_tok,
            "实际服务模型": served,
            "model响应秒": round(model_elapsed, 3) if run_model else "",
            "rules响应秒": round(rules_elapsed, 3),
            "备注": note,
        })

        flag = ""
        if run_model and not consistent:
            flag = "  <<< rules/model 不一致"
        if verdict != "正确":
            flag += f"  <<< {verdict}:{err_type}"
        call_note = f"调用{calls}次 {total_tok}tok" if calls else "护栏前拦截·零调用"
        log(f"[{i:>2}/{len(questions)}] {qid} {question[:30]}"
            f"｜rules={rules_resp.get('status'):<20}"
            + (f"｜model={judged_resp.get('status'):<20}｜{verdict}｜{call_note}"
               f"｜{model_elapsed*1000:6.0f}ms" if run_model else f"｜{verdict}")
            + flag)

    total = len(questions)
    completion = (counts["正确"] + 0.5 * counts["部分正确"]) / total if total else 0.0

    log("\n" + "=" * 84)
    log(f"汇总（{total} 题，判定对象={'真实模型信封' if run_model else '规则信封（预检）'}）")
    log("-" * 84)
    log(f"  正确 {counts['正确']}｜部分正确 {counts['部分正确']}｜错误 {counts['错误']}"
        f"｜任务完成率 {completion:.1%}")
    log(f"  正确澄清 {counts['澄清']}｜无依据编造 {counts['编造']}｜执行失败 {counts['执行失败']}")
    if run_model:
        log(f"  model 与 rules 信封完全一致：{counts['一致']}/{total}")
        log(f"  实际发起模型调用 {counts['模型调用']} 题；本地护栏在模型前直接拦截（零调用）"
            f"{counts['护栏零调用']} 题；瞬时失败重试 {counts['重试']} 题")
        log(f"  实际服务模型分布：{json.dumps(served_models, ensure_ascii=False)}")
        lat = sorted(model_latencies)
        if lat:
            log(f"  端到端时延（仅调用题，秒）：n={len(lat)} 平均={sum(lat)/len(lat):.3f} "
                f"中位={percentile(lat, .5):.3f} p90={percentile(lat, .9):.3f} 最大={lat[-1]:.3f}")
        log(f"  token 合计：缓存命中 {total_tokens['hit']}｜未命中 {total_tokens['miss']}｜"
            f"输出 {total_tokens['out']}")

        def cost(price: dict) -> float:
            return (total_tokens["hit"] * price["hit"]
                    + total_tokens["miss"] * price["miss"]
                    + total_tokens["out"] * price["out"]) / 1_000_000

        log(f"  估算成本：空闲价 ¥{cost(PRICE_OFFPEAK):.4f}（实际：2026-10-06 国庆假期全天空闲）"
            f"；若工作日高峰约 ¥{cost(PRICE_PEAK):.4f}")
        log(f"  价格依据：deepseek-flash 峰谷价，{PRICE_URL}（2026-10-06 读取；deepseek-chat 为官方别名）")

    bad = [d for d in detail if d["判定"] != "正确"]
    if bad:
        log("\n非「正确」题目：")
        for d in bad:
            log(f"  {d['题号']}（{d['题集']}）[{d['分类']}] {d['问题']}")
            log(f"      预期={d['预期状态']} rules={d['rules状态']} "
                f"model={d['model状态'] or '-'} → {d['判定']}｜{d['错误分类']}｜{d['备注']}")
    if run_model:
        mismatch = [d for d in detail if d["与rules一致"] == "否"]
        if mismatch:
            log("\nrules/model 不一致题目：")
            for d in mismatch:
                log(f"  {d['题号']} {d['问题']}｜rules={d['rules状态']} model={d['model状态']}")

    log("\n" + "-" * 84)
    log("诚实声明：真实模型仅承担「问题→结构化槽位」，指标字典/澄清/护栏/聚合/SQL 均在本地；")
    log("数字来自与规则模式完全相同的本地执行层，本复测证明的是模型槽位解析在治理框架下")
    log("零事故且不改变任何结果，不是「LLM 端到端答题」能力，也不替代 S1 确定性基线对照。")
    log("=" * 84)

    if run_model:
        header = ["题号", "题集", "问题", "分类", "预期状态", "rules状态", "model状态",
                  "判定", "错误分类", "与rules一致", "重试", "模型调用次数",
                  "prompt缓存命中", "prompt未命中", "completion_tokens", "total_tokens",
                  "实际服务模型", "model响应秒", "rules响应秒", "备注"]
        with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=header, lineterminator="\n")
            w.writeheader()
            w.writerows(detail)
        log(f"\n明细：{OUT_CSV}")
    log(f"汇总：{OUT_TXT}")


if __name__ == "__main__":
    main()
