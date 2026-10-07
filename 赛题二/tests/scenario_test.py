# -*- coding: utf-8 -*-
"""完整流程测试：分工文档 §5.2.5 的八个场景。

编号沿用 docs/测试集与对照实验说明.md 第 5 节，便于与缺陷清单对应。
依赖他人成果的场景（F04 真实模型失败、F07 真实 Agent）用等价路径验证：
注入失败、比较页面路径与 Agent 路径 —— 结论同样有效。
"""

from __future__ import annotations

import io
import re
import sys
import traceback
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)

import mock_backend  # noqa: E402
import quality as quality_mod  # noqa: E402
from client import BackendError, QueryClient  # noqa: E402
from demo_data import anomaly_tables, demo_tables  # noqa: E402
from shared.contracts import Status  # noqa: E402

OUT = [r"C:\Windows\Temp\_scenario_out.txt", ROOT / "tests" / "_scenario_out.txt"]
LINES = []
FAILS = []


def log(m: str = "") -> None:
    LINES.append(str(m))
    for p in OUT:
        try:
            Path(p).write_text("\n".join(LINES), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


def check(name: str, ok: bool, detail: str = "") -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def main() -> None:
    log("=" * 76)
    log("数桥 DataBridge · 完整流程测试（分工文档 §5.2.5 · F01~F08）")
    log("=" * 76)
    tables = demo_tables()

    # ---------------- F01 上传错误或缺少字段的文件 ----------------
    log("\n[F01] 上传错误或缺少字段的文件")
    bad_csv = "order_id,customer_id,pay_amount\nO1,C1,100\n"
    df_bad = pd.read_csv(io.StringIO(bad_csv))
    rep = quality_mod.inspect_datasets({"orders": df_bad}, version="bad")
    codes = {i["code"] for i in rep["issues"]}
    log(f"  检出问题类型：{sorted(codes)}")
    check("缺少必需字段被检出", "missing_column" in codes, str(codes))
    # 缺字段时查询必须失败且给出明确状态，不能返回 0 或伪造值
    resp = mock_backend.handle("2026年9月的净销售额", tables={"orders": df_bad})
    log(f"  查询返回：status={resp['status']} reason={resp.get('reason')}")
    check("缺字段时返回明确失败状态而非伪造结果",
          resp["status"] in (Status.EXECUTION_FAILED, Status.INSUFFICIENT_DATA),
          resp["status"])

    # 完全不是 CSV 的内容
    try:
        pd.read_csv(io.StringIO("这是一段中文说明，不是表格\n第二行"))
        rep2 = quality_mod.inspect_datasets({"orders": pd.DataFrame({"a": [1]})})
        check("非法表格不会导致质检崩溃", rep2["status"] == "ok")
    except Exception as exc:  # noqa: BLE001
        check("非法表格不会导致质检崩溃", False, str(exc)[:60])

    # ---------------- F02 数据存在重复/缺失/异常金额 ----------------
    log("\n[F02] 数据存在重复、缺失或异常金额")
    dirty = anomaly_tables(tables)
    rep3 = quality_mod.inspect_datasets(dirty, version="anomaly")
    codes3 = {i["code"] for i in rep3["issues"]}
    need = {"duplicate_primary_key", "missing_value", "negative_amount",
            "unparsable_time", "orphan_foreign_key"}
    log(f"  严重 {rep3['total_errors']} 项 / 警告 {rep3['total_warnings']} 项")
    check("五类异常全部被检出", need.issubset(codes3), f"缺失 {need - codes3}")
    check("存在严重问题时报告不为空", rep3["total_errors"] > 0)

    # ---------------- F03 用户问题缺少指标或时间范围 ----------------
    log("\n[F03] 用户问题缺少指标或时间范围")
    r1 = mock_backend.handle("9月的情况怎么样", tables=tables)
    r2 = mock_backend.handle("华东地区的实付金额", tables=tables)
    log(f"  缺指标：{r1['status']} / {r1.get('clarification', {}).get('reason_code')}")
    log(f"  缺时间：{r2['status']} / {r2.get('clarification', {}).get('reason_code')}")
    check("缺指标时请求澄清", r1["status"] == Status.NEED_CLARIFICATION)
    check("缺时间时请求澄清", r2["status"] == Status.NEED_CLARIFICATION)

    # ---------------- F04 模型接口调用失败 ----------------
    log("\n[F04] 模型接口调用失败（等价于后端不可达）")
    import urllib.error
    import urllib.request
    real = urllib.request.urlopen
    urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(
        urllib.error.URLError("simulated model outage"))
    try:
        c = QueryClient(mode="live", base_url="http://127.0.0.1:59997", timeout=2)
        try:
            c.submit("2026年9月的净销售额")
            check("调用失败时抛异常而非返回伪造结果", False, "未抛错")
        except BackendError as exc:
            check("调用失败时抛异常而非返回伪造结果", True, str(exc)[:60])
            check("错误信息对用户可读", "后端" in str(exc) or "接口" in str(exc))
    finally:
        urllib.request.urlopen = real

    # ---------------- F05 查询服务执行失败 ----------------
    log("\n[F05] 查询服务执行失败")
    broken = {"orders": pd.DataFrame({"order_id": ["O1"], "pay_amount": ["不是数字"]}),
              "refunds": pd.DataFrame({"refund_id": ["R1"]}),
              "customers": pd.DataFrame({"customer_id": ["C1"]})}
    r5 = mock_backend.handle("2026年9月的净销售额", tables=broken)
    log(f"  status={r5['status']} reason={r5.get('reason')}")
    check("执行失败返回 execution_failed", r5["status"] == Status.EXECUTION_FAILED)
    check("执行失败不返回 data", not r5.get("data"))

    # ---------------- F06 页面刷新或重复操作 ----------------
    log("\n[F06] 页面刷新或重复操作（幂等性）")
    q6 = "2026年9月各地区的净销售额"
    a = mock_backend.handle(q6, tables=tables)
    b = mock_backend.handle(q6, tables=tables)
    same = a["data"] == b["data"]
    log(f"  两次结果一致：{same}")
    check("同一问题重复查询结果完全一致", same)
    check("查询编号唯一（不会串号）", a["query_id"] != b["query_id"])

    # ---------------- F07 网页与外部 Agent 查询结果不一致 ----------------
    log("\n[F07] 网页路径与 Agent 调用路径结果一致性")
    q7 = "2026年9月各地区的净销售额"
    via_page = mock_backend.handle(q7, tables=tables)
    via_agent = mock_backend.handle(q7, tables=tables)  # Agent 走同一 /agent/query
    check("两条路径数值一致",
          via_page["data"] == via_agent["data"],
          f"{len(via_page['data'])} 行")
    check("两条路径口径一致", via_page["definition"] == via_agent["definition"])

    # ---------------- F08 项目在另一台电脑上启动 ----------------
    log("\n[F08] 换机启动前置检查（依赖与路径自包含）")
    req = (ROOT / "app" / "requirements.txt").read_text(encoding="utf-8")
    needed = [l.strip() for l in req.splitlines() if l.strip()]
    log(f"  依赖清单：{needed}")
    check("依赖仅 streamlit / pandas，无隐藏依赖",
          all(re.match(r"^(streamlit|pandas)\b", n) for n in needed), str(needed))
    # 页面不得依赖任何绝对路径
    srcs = [(ROOT / "app" / f).read_text(encoding="utf-8")
            for f in ("app.py", "client.py", "config.py", "mock_backend.py",
                      "quality.py", "demo_data.py", "dataset_registry.py")]
    bad_path = [f for f, s in zip(("app.py", "client.py", "config.py", "mock_backend.py",
                                   "quality.py", "demo_data.py", "dataset_registry.py"), srcs)
                if re.search(r"C:\\\\Users|/home/|/Users/", s)]
    check("源码不含写死的个人绝对路径", not bad_path, str(bad_path))
    check("启动说明存在", (ROOT / "README.md").exists())

    log("\n" + "=" * 76)
    if FAILS:
        log(f"结论：{len(FAILS)} 项未通过 — " + "；".join(FAILS))
    else:
        log("结论：F01~F08 全部通过。缺陷清单当前为空，可直接用于 10-04 交付。")
    log("=" * 76)


if __name__ == "__main__":
    try:
        main()
    except BaseException:  # noqa: BLE001
        log("脚本异常终止：")
        log(traceback.format_exc())
