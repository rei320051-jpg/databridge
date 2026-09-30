# -*- coding: utf-8 -*-
"""数桥 DataBridge · 可信取数平台 —— 成员 3 最小查询页面（9/30 交付）

对应分工文档：
  §5.2.1 产品操作流程（8 步）
  §5.2.2 四个功能区域：数据接入区 / 业务字典区 / 智能取数区 / 结果依据区
  §5.4   验收标准：每次成功查询都能查看口径和来源

运行：
  streamlit run app/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
for _p in (str(ROOT_DIR), str(APP_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from shared.contracts import (  # noqa: E402
    ALLOWED_FILTER_KEYS,
    AMBIGUOUS_METRIC_TERMS,
    CONTRACT_DATE,
    DATASET_COVERAGE,
    DATASET_VERSION,
    DIMENSION_SPEC,
    MAX_CLARIFICATION_ROUNDS,
    METRIC_SPEC,
    MODULE_VERSION,
    PRESET_EXAMPLES,
    REASON_LABEL,
    STATUS_LABEL,
    STATUS_SEVERITY,
    Status,
)
import config as app_config  # noqa: E402
import client as client_mod  # noqa: E402
import quality as quality_mod  # noqa: E402
import dataset_registry as registry  # noqa: E402

# ---------------------------------------------------------------------------
# 页面基础
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="数桥 DataBridge · 可信取数平台",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# 全局样式：只做轻量增强，不引入额外依赖，也不改变任何业务逻辑
# ---------------------------------------------------------------------------
APP_CSS = """
<style>
  .block-container { padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1240px; }

  /* ---- 动效基调：短、轻、克制；尊重系统「减少动态效果」设置 ---- */
  @keyframes db-fade-up {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @keyframes db-shimmer {
    0%   { background-position: -480px 0; }
    100% { background-position: 480px 0; }
  }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation: none !important; transition: none !important; }
  }

  .db-hero {
    background: linear-gradient(135deg, #f4f7ff 0%, #ecf2ff 100%);
    border: 1px solid #d9e2f4; border-radius: 12px;
    padding: 18px 22px; margin-bottom: 16px;
    animation: db-fade-up .35s ease both;
  }
  .db-hero h1 { font-size: 1.5rem; margin: 0 0 6px 0; color: #12233f; font-weight: 700; }
  .db-hero p  { margin: 0; color: #47546f; font-size: .92rem; line-height: 1.65; }
  .db-tags { margin-top: 11px; display: flex; gap: 8px; flex-wrap: wrap; }
  .db-tag {
    background: #fff; border: 1px solid #d3dded; color: #2b3d5c;
    border-radius: 999px; padding: 3px 11px; font-size: .78rem;
    transition: background .15s ease, border-color .15s ease;
  }
  .db-tag:hover { background: #eef3ff; border-color: #b9c9e6; }

  .db-card {
    background: rgba(255, 255, 255, .82);
    backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
    border: 1px solid #e2e7ef; border-radius: 10px;
    padding: 13px 16px; margin: 10px 0;
    transition: box-shadow .18s ease, transform .18s ease;
    animation: db-fade-up .35s ease both;
  }
  .db-card:hover { box-shadow: 0 8px 24px rgba(31, 55, 109, .10); transform: translateY(-1px); }
  .db-card h4 { margin: 0 0 6px 0; font-size: .95rem; color: #12233f; }
  .db-card p  { margin: 0; font-size: .86rem; color: #47546f; line-height: 1.7; }
  .db-note { font-size: .82rem; color: #6b7891; }

  /* ---- KPI 指标卡：毛玻璃 + 悬浮抬升 ---- */
  div[data-testid="stMetric"] {
    background: rgba(255, 255, 255, .72);
    backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
    border: 1px solid rgba(214, 224, 240, .9); border-radius: 12px;
    padding: 14px 16px;
    box-shadow: 0 2px 10px rgba(31, 55, 109, .05);
    transition: transform .18s ease, box-shadow .18s ease;
    animation: db-fade-up .35s ease both;
  }
  div[data-testid="stMetric"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 26px rgba(31, 55, 109, .13);
  }
  div[data-testid="stMetricValue"] { font-size: 1.35rem; font-weight: 650; }

  /* ---- 结果区：表格、图表卡片化，内容出现时淡入 ----
     选择器来自真实 DOM 探查：图表是 stVegaLiteChart，表格外框是 stDataFrameResizable。 */
  [data-testid="stDataFrame"], [data-testid="stVegaLiteChart"] {
    animation: db-fade-up .4s ease both;
  }
  div[data-testid="stDataFrameResizable"],
  div[data-testid="stVegaLiteChart"] {
    background: rgba(255, 255, 255, .72) !important;
    backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
    border: 1px solid #e6ecf5 !important; border-radius: 10px !important;
    padding: 8px 10px; box-shadow: 0 2px 10px rgba(31, 55, 109, .05);
    transition: box-shadow .18s ease, transform .18s ease;
  }
  div[data-testid="stDataFrameResizable"]:hover,
  div[data-testid="stVegaLiteChart"]:hover {
    box-shadow: 0 8px 22px rgba(31, 55, 109, .10); transform: translateY(-1px);
  }

  /* ---- 对话与状态提示淡入 ---- */
  [data-testid="stChatMessage"] { animation: db-fade-up .3s ease both; }
  [data-testid="stAlert"] { animation: db-fade-up .3s ease both; }
  div[data-testid="stHorizontalBlock"] > div { gap: .25rem; }

  /* ---- 查询骨架屏（shimmer）：仅在查询执行期间渲染，不人为制造延迟 ---- */
  .db-skeleton {
    background: rgba(255, 255, 255, .8); border: 1px solid #e6ecf5;
    border-radius: 12px; padding: 16px 18px; margin: 10px 0;
    animation: db-fade-up .2s ease both;
  }
  .db-skeleton .sk-bar {
    height: 14px; border-radius: 7px; margin: 10px 0;
    background: linear-gradient(90deg, #eef2f8 25%, #e2e9f4 37%, #eef2f8 63%);
    background-size: 960px 100%;
    animation: db-shimmer 1.25s linear infinite;
  }
  .db-skeleton .sk-title { height: 20px; width: 34%; }
  .db-skeleton .sk-kpi-row { display: flex; gap: 12px; margin: 12px 0 6px; }
  .db-skeleton .sk-kpi {
    flex: 1; height: 64px; border-radius: 10px;
    background: linear-gradient(90deg, #eef2f8 25%, #e2e9f4 37%, #eef2f8 63%);
    background-size: 960px 100%; animation: db-shimmer 1.25s linear infinite;
  }
  .db-skeleton .sk-w70 { width: 70%; } .db-skeleton .sk-w45 { width: 45%; }
</style>
"""
st.markdown(APP_CSS, unsafe_allow_html=True)

SKELETON_HTML = """
<div class="db-skeleton" aria-busy="true" aria-label="正在查询">
  <div class="sk-bar sk-title"></div>
  <div class="sk-kpi-row"><div class="sk-kpi"></div><div class="sk-kpi"></div><div class="sk-kpi"></div></div>
  <div class="sk-bar sk-w70"></div><div class="sk-bar"></div>
  <div class="sk-bar sk-w45"></div>
</div>
"""


def _show_skeleton() -> None:
    """查询执行期间展示骨架屏；真实耗时多长就显示多长，不注入任何人为延迟。"""
    st.markdown(SKELETON_HTML, unsafe_allow_html=True)

LABEL_MAP = {code: spec["label"] for code, spec in METRIC_SPEC.items()}
LABEL_MAP.update({code: spec["label"] for code, spec in DIMENSION_SPEC.items()})
LABEL_MAP["prev_value"] = "上一期"
LABEL_MAP["mom_pct"] = "环比 %"


@st.cache_data(show_spinner="正在生成内置演示数据…")
def _cached_demo():
    from demo_data import demo_tables
    tables = demo_tables()
    return {k: v.copy() for k, v in tables.items()}


@st.cache_data(show_spinner="正在生成异常测试数据…")
def _cached_anomaly():
    from demo_data import anomaly_tables
    tables = anomaly_tables()
    return {k: v.copy() for k, v in tables.items()}


def _init_state() -> None:
    ss = st.session_state
    ss.setdefault("chat_log", [])
    ss.setdefault("last_response", None)
    ss.setdefault("pending_clarification", None)
    ss.setdefault("pending_question", "")
    ss.setdefault("resolved_context", {})
    ss.setdefault("history", [])
    ss.setdefault("agent_result", None)
    ss.setdefault("datasets", [])           # 数据集注册历史（仅元信息）
    ss.setdefault("active_dataset", None)   # 当前激活数据集的元信息
    ss.setdefault("confirmed_metrics", set())  # 第 3 步：已确认口径的指标
    ss.setdefault("confirmed_fields", set())   # 第 3 步：已确认含义的字段


def _reset_query() -> None:
    ss = st.session_state
    ss["chat_log"] = []
    ss["last_response"] = None
    ss["pending_clarification"] = None
    ss["pending_question"] = ""
    ss["resolved_context"] = {}
    ss["history"] = []


def _register_dataset(tables: dict, source: str) -> dict:
    """把当前数据注册成一个有版本号的数据集。

    版本号由内容哈希生成而非时间戳，因此同一份数据重复上传版本不变，
    查询结果里的数据集版本才是真正可追溯的。
    """
    ss = st.session_state
    rec = registry.make_record(tables, source)
    versions = [d["version"] for d in ss["datasets"]]
    if rec["version"] not in versions:
        ss["datasets"] = [rec] + ss["datasets"][:9]  # 只保留最近 10 条，避免内存膨胀
    ss["active_dataset"] = rec
    ss["active_tables"] = tables  # 供业务字典区按实际字段渲染确认清单
    _client.set_tables(tables)
    _client.dataset_version = rec["version"]
    return rec


_init_state()

# ---------------------------------------------------------------------------
# 侧边栏
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### 运行配置")
    mode_label = st.radio(
        "后端模式",
        ["mock（本地模拟）", "live（对接成员 1 服务）"],
        index=0 if app_config.BACKEND_MODE == "mock" else 1,
        help="接口未就绪时用 mock 跑通全流程；成员 1 的服务上线后切到 live，页面代码无需改动。",
    )
    backend_mode = "mock" if mode_label.startswith("mock") else "live"

    api_url = st.text_input("后端地址", value=app_config.API_BASE_URL,
                            disabled=(backend_mode == "mock"))

    health = None
    if backend_mode == "live":
        if st.button("测试连接"):
            st.session_state["health"] = None
        _c = client_mod.QueryClient(mode="live", base_url=api_url,
                                    timeout=app_config.API_TIMEOUT)
        health = _c.health()

    st.divider()
    st.markdown("### 契约状态")
    st.caption(f"接口契约版本：v{MODULE_VERSION}（{CONTRACT_DATE}）")
    st.caption(f"数据集版本：{DATASET_VERSION}")
    st.caption(f"业务基准日：{DATASET_COVERAGE['end']}")
    st.caption(f"数据覆盖：{DATASET_COVERAGE['start']} ~ {DATASET_COVERAGE['end']}")
    st.caption("功能冻结日：2026-10-08")

    st.divider()
    if st.button("清空对话与查询记录"):
        _reset_query()
        st.rerun()

    st.caption("页面版本 v0.1 · 2026-09-30 · 成员 3")

# ---------------------------------------------------------------------------
# 数据源装载（先于 client，供 mock 模式使用）
# ---------------------------------------------------------------------------

_client = client_mod.QueryClient(mode=backend_mode, base_url=api_url,
                                 timeout=app_config.API_TIMEOUT)

st.markdown(
    '<div class="db-hero">'
    "<h1>数桥 DataBridge · 可信取数平台</h1>"
    "<p>面向 AI Agent 的可信取数平台。每一个数字都附带"
    "<b>指标口径、来源表、数据集版本与可追溯的查询记录</b>；"
    "当数据无法支持结论时，明确说明缺什么，而不是编一个答案。</p>"
    '<div class="db-tags">'
    '<span class="db-tag">只读 · 不修改任何业务数据</span>'
    '<span class="db-tag">5 个固定指标口径</span>'
    '<span class="db-tag">口径不明确时先澄清</span>'
    '<span class="db-tag">最多澄清 2 轮</span>'
    '<span class="db-tag">零售订单分析场景</span>'
    "</div></div>",
    unsafe_allow_html=True,
)
st.caption(
    "模拟业务数据 · 数据覆盖 2026-06-01 ~ 2026-09-30 · 数据集版本 "
    f"{DATASET_VERSION} · 接口契约 v{MODULE_VERSION}"
)

tab_data, tab_dict, tab_query, tab_evidence, tab_agent = st.tabs(
    ["① 数据接入", "② 业务字典", "③ 智能取数", "④ 结果依据", "⑤ Agent 调用回放"]
)


# ===========================================================================
# ① 数据接入区
# ===========================================================================

def render_data_zone() -> dict:
    st.subheader("数据接入区")
    st.caption(
        "对应分工文档 §5.2.2「数据接入区」。"
        "正式的数据导入与质量检查由成员 1 的 `/datasets/inspect` 提供，"
        "此处为页面侧对照实现，用于接口未就绪时演示与交叉验证。"
    )

    uploaded = st.file_uploader(
        "上传业务数据（CSV，可多选）", type=["csv"], accept_multiple_files=True,
        help="文件名需包含 order / refund / customer 之一，用于识别订单表、退款表、客户表。",
    )
    use_anomaly = st.checkbox(
        "载入异常测试数据集（人为注入重复主键、缺失值、负金额、脏时间、悬空外键）",
        value=False,
        help="对应分工文档 §5.2.5 要求的异常场景测试。",
    )

    tables: dict = {}
    source = ""
    if uploaded:
        for f in uploaded:
            name = quality_mod.infer_table_name(f.name)
            try:
                tables[name] = pd.read_csv(f)
            except Exception as exc:  # noqa: BLE001
                st.error(f"读取 `{f.name}` 失败：{exc}")
        source = "用户上传：" + "、".join(f"{k}（{v.shape[0]} 行）" for k, v in tables.items())
    elif use_anomaly:
        tables = _cached_anomaly()
        source = "内置异常测试数据（模拟数据，用于验证质量检查能力，不参与演示）"
    else:
        tables = _cached_demo()
        source = "内置演示数据（模拟业务数据，正式数据集由成员 1 交付）"

    if not tables:
        st.info("请上传 CSV 文件，或使用内置演示数据。")
        return tables

    # 分工文档 §5.2.1 第 1 步：上传后注册为数据集，并生成内容感知的版本号
    rec = _register_dataset(tables, source)
    report = quality_mod.inspect_datasets(tables, version=rec["version"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("数据表数量", len(tables))
    c2.metric("订单总行数", f"{report['tables'][0]['rows']:,}" if report["tables"] else "0")
    c3.metric("严重问题", report["total_errors"])
    c4.metric("警告", report["total_warnings"])

    st.markdown(
        '<div class="db-card"><h4>当前数据集（第 1 步·注册结果）</h4>'
        '<p><span class="db-note">数据集版本</span> <code>'
        + rec["version"] +
        '</code>　<span class="db-note">更新时间</span> '
        + rec["created_at"] +
        '<br><span class="db-note">数据来源</span> ' + source +
        '<br><span class="db-note">数据表构成</span> '
        + "、".join(f"{k}（{v['rows']:,} 行 / {v['cols']} 字段）"
                   for k, v in rec["tables"].items()) +
        "</p></div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "版本号由**数据内容哈希**生成，不是时间戳：内容变化则版本变化，"
        "同一份数据重复上传版本保持不变。该版本号会随每次查询结果一起返回，"
        "使得「结果依据区」里的来源真正可追溯（分工文档 §5.4）。"
    )

    if len(st.session_state["datasets"]) > 1:
        with st.expander(f"数据集上传历史（{len(st.session_state['datasets'])} 条）"):
            st.dataframe(pd.DataFrame([{
                "数据集版本": d["version"],
                "来源": d["source"][:40],
                "更新时间": d["created_at"],
                "总行数": f"{d['total_rows']:,}",
            } for d in st.session_state["datasets"]]), hide_index=True)
            st.caption("历史记录仅保留元信息，不与数据一并驻留内存，因此无法切回旧版本数据。")

    st.markdown("**数据集列表**")
    rows = []
    for r in report["tables"]:
        rows.append({
            "表名": r["name"],
            "行数": f"{r['rows']:,}",
            "字段数": r["columns"],
            "主键": r["primary_key"],
            "严重问题": r["error_count"],
            "警告": r["warning_count"],
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True)

    st.markdown("**数据质量问题**")
    if not report["issues"]:
        st.success("未发现数据质量问题。可直接进行查询。")
    else:
        issues_df = pd.DataFrame([{
            "级别": {"error": "严重", "warning": "警告", "info": "提示"}[i["level"]],
            "表": i["table"],
            "字段": i["field"],
            "数量": i["count"],
            "问题": i["message"],
            "对查询结果的影响": i["impact"],
        } for i in report["issues"]])
        order = {"严重": 0, "警告": 1, "提示": 2}
        issues_df = issues_df.sort_values("级别", key=lambda s: s.map(order))
        st.dataframe(issues_df, hide_index=True)

        if report["total_errors"]:
            st.error(
                "当前数据存在严重问题。在这些问题修复前，任何查询结果都不能作为正确结论使用 —— "
                "这是「可信取数」的基本要求。"
            )

    with st.expander("查看字段类型明细"):
        for r in report["tables"]:
            st.markdown(f"**{r['name']}**（{r['rows']:,} 行）")
            st.dataframe(
                pd.DataFrame([{"字段": k, "推断类型": v} for k, v in r["field_types"].items()]),
                hide_index=True,
            )

    with st.expander("下载测试数据"):
        st.caption("用于成员 3 的测试执行，以及与成员 1 的质检接口结果做交叉验证。")
        for name, df in tables.items():
            st.download_button(
                f"下载 {name}.csv（{len(df):,} 行）",
                data=df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{name}.csv",
                mime="text/csv",
                key=f"dl_{name}_{use_anomaly}",
            )
    return tables


# ===========================================================================
# ② 业务字典区
# ===========================================================================

def render_dictionary_zone() -> None:
    st.subheader("业务字典区")
    st.caption(
        "对应分工文档 §5.2.2「业务字典区」。"
        "本页内容直接来自 `shared/contracts.py`，与成员 1 的指标计算、成员 2 的提示词同源，"
        "保证三方使用同一套口径。"
    )

    st.markdown("**核心指标（首版固定 5 个）**")
    st.dataframe(pd.DataFrame([{
        "指标": spec["label"],
        "编码": code,
        "单位": spec["unit"],
        "业务口径": spec["definition"],
        "计算逻辑": spec["formula"],
        "同义词": "、".join(spec["synonyms"]),
        "来源表": "、".join(spec["source_tables"]),
    } for code, spec in METRIC_SPEC.items()]), hide_index=True)

    st.markdown("**可分组维度**")
    st.dataframe(pd.DataFrame([{
        "维度": spec["label"],
        "编码": code,
        "字段名": spec["column"],
        "取值": "、".join(spec["values"]),
        "常见说法": "、".join(spec["synonyms"]),
    } for code, spec in DIMENSION_SPEC.items()]), hide_index=True)

    st.markdown("**表关系**")
    st.code(
        "customers (customer_id PK, region, customer_type)\n"
        "    1 ──── N  orders (order_id PK, customer_id FK, pay_status, pay_time, pay_amount)\n"
        "                    1 ──── N  refunds (refund_id PK, order_id FK, refund_status, refund_time, refund_amount)\n"
        "\n"
        "关系基数提示：一个订单可以对应多条退款记录。\n"
        "若直接 JOIN refunds 后再 SUM(orders.pay_amount)，实付金额会被重复累加。\n"
        "正确做法：先在 refunds 侧按 order_id 预聚合，再与 orders 左连接。",
        language="text",
    )

    st.markdown("**歧义词表（命中必须澄清，不得使用默认口径直接回答）**")
    st.dataframe(pd.DataFrame([{
        "用户可能说": term,
        "可能的指标": " 或 ".join(METRIC_SPEC[c]["label"] for c in codes),
        "处理方式": "向用户澄清",
    } for term, codes in AMBIGUOUS_METRIC_TERMS.items()]), hide_index=True)

    # ---------------------------------------------------------------
    # 第 3 步：查看或确认字段及指标含义（分工文档 §5.2.1）
    # ---------------------------------------------------------------
    st.divider()
    st.markdown("**第 3 步 · 确认口径后再查询**")
    st.caption(
        "勾选表示你已核对过该口径与本方业务理解一致。"
        "未确认不会阻止查询，平台只会在提问时提示你尚未确认。\n\n"
        "这一步存在的理由：口径不一致是取数结果互相矛盾的最常见原因，"
        "与其事后争论，不如在提问前对齐。"
    )

    m_cols = st.columns(2)
    confirmed = st.session_state["confirmed_metrics"]
    for i, (code, spec) in enumerate(METRIC_SPEC.items()):
        picked = m_cols[i % 2].checkbox(
            f"{spec['label']}（{spec['unit']}）",
            value=code in confirmed,
            key=f"conf_metric_{code}",
            help=f"{spec['definition']}\n\n计算：{spec['formula']}",
        )
        if picked:
            confirmed.add(code)
        else:
            confirmed.discard(code)
    st.session_state["confirmed_metrics"] = confirmed

    n_ok = len(confirmed)
    st.progress(n_ok / len(METRIC_SPEC),
                text=f"已确认 {n_ok} / {len(METRIC_SPEC)} 个核心指标口径")

    tables_now = st.session_state.get("active_tables") or {}
    if tables_now:
        with st.expander("按当前数据集核对字段含义"):
            confirmed_f = st.session_state["confirmed_fields"]
            for tname, df in tables_now.items():
                fields = [str(c) for c in df.columns]
                ok = st.checkbox(
                    f"已核对 `{tname}` 的 {len(fields)} 个字段（{len(df):,} 行）",
                    value=tname in confirmed_f, key=f"conf_field_{tname}",
                    help="、".join(fields),
                )
                if ok:
                    confirmed_f.add(tname)
                else:
                    confirmed_f.discard(tname)
                st.caption("、".join(fields))
            st.session_state["confirmed_fields"] = confirmed_f

    st.markdown("**已冻结的接口字段**")
    st.caption("功能冻结日 2026-10-08 之后，以下字段原则上只修 bug 不变更。")
    st.code(
        '查询计划  {"metric","date_start","date_end","group_by","filters","sort","limit","comparison"}\n'
        '结果信封  {"status","message","query_id","dataset_version","executed_at"}\n'
        '成功附加  {"data","columns","definition","unit","applied_filters","source_tables",\n'
        '           "generated_sql","warnings","row_count","truncated"}\n'
        '澄清附加  {"clarification"} → {"id","target_field","reason_code","question",\n'
        '           "options","allow_free_text","resolved_context","round"}\n'
        '失败附加  {"reason","missing","suggestion","retryable"}',
        language="text",
    )


# ===========================================================================
# ③ 智能取数区
# ===========================================================================

def _submit(question: str) -> None:
    ss = st.session_state
    ss["chat_log"].append({"role": "user", "text": question})
    try:
        resp = _client.submit(question, context=ss.get("resolved_context") or {})
    except client_mod.BackendError as exc:
        ss["last_response"] = {
            "status": Status.EXECUTION_FAILED,
            "message": str(exc),
            "reason": "backend_unreachable",
            "missing": ["后端服务"],
            "suggestion": "请确认成员 1 的服务已启动，或切换到 mock 模式继续自测。",
            "retryable": True,
            "warnings": [],
        }
        ss["pending_clarification"] = None
        ss["chat_log"].append({"role": "system", "text": f"调用后端失败：{exc}"})
        return

    ss["last_response"] = resp
    if resp.get("status") == Status.NEED_CLARIFICATION:
        ss["pending_clarification"] = resp["clarification"]
        ss["pending_question"] = question
        ss["chat_log"].append({"role": "assistant", "text": resp["clarification"]["question"]})
    else:
        ss["pending_clarification"] = None
        ss["resolved_context"] = resp.get("context", {}) or {}
        ss["chat_log"].append({"role": "assistant", "text": client_mod.summarize(resp)})
        ss["history"].append(resp)
    ss["chat_log"] = ss["chat_log"][-app_config.CHAT_HISTORY_LIMIT:]


def _submit_clarification(choice: str, free_text: str | None = None) -> None:
    ss = st.session_state
    clr = ss.get("pending_clarification") or {}
    label = next((o["label"] for o in clr.get("options", []) if o["value"] == choice), choice)
    ss["chat_log"].append({"role": "user", "text": f"（澄清）{label}"})
    try:
        resp = _client.resolve_clarification(
            clr, choice=choice, question=ss.get("pending_question", ""),
            context=clr.get("resolved_context") or {}, free_text=free_text,
        )
    except client_mod.BackendError as exc:
        st.error(f"提交澄清失败：{exc}")
        return

    ss["last_response"] = resp
    if resp.get("status") == Status.NEED_CLARIFICATION:
        ss["pending_clarification"] = resp["clarification"]
    else:
        ss["pending_clarification"] = None
        ss["resolved_context"] = resp.get("context", {}) or {}
        ss["chat_log"].append({"role": "assistant", "text": client_mod.summarize(resp)})
        ss["history"].append(resp)


def _status_banner(resp: dict) -> None:
    st_txt = resp.get("status")
    sev = STATUS_SEVERITY.get(st_txt, "info")
    label = STATUS_LABEL.get(st_txt, st_txt)
    msg = resp.get("message", "")
    body = f"**{label}** —— {msg}"
    if resp.get("reason") and sev != "info":
        body += f"\n\n原因码：`{resp['reason']}`"
    if resp.get("suggestion"):
        body += f"\n\n建议：{resp['suggestion']}"
    if resp.get("missing"):
        body += f"\n\n缺少：{'、'.join(resp['missing'])}"
    {"info": st.success, "warning": st.warning, "error": st.error}[sev](body)


def _render_success(resp: dict) -> None:
    df = pd.DataFrame(resp["data"])
    if df.empty:
        st.warning("查询返回 0 行。请检查时间范围与筛选条件。")
        return
    df = df.rename(columns=LABEL_MAP)
    metric_label = LABEL_MAP.get(resp["metric"], resp["metric"])
    if "上一期" in df.columns and metric_label in df.columns:
        prev = pd.to_numeric(df["上一期"], errors="coerce")
        cur = pd.to_numeric(df[metric_label], errors="coerce")
        df["环比 %"] = ((cur - prev) / prev.replace(0, pd.NA) * 100).round(2)

    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    group_cols = [c for c in df.columns if c not in num_cols]

    # 关键指标卡：先给结论，再给明细。评委和运营看的是这一行。
    unit = resp.get("unit", "")
    kpi = st.columns(3)
    if metric_label in df.columns:
        vals = pd.to_numeric(df[metric_label], errors="coerce")
        total = float(vals.sum())
        kpi[0].metric(metric_label, f"{total:,.0f} {unit}" if unit else f"{total:,.0f}",
                      help=f"{resp.get('definition', '')}")
    else:
        kpi[0].metric("返回行数", len(df))

    if group_cols:
        kpi[1].metric("分组数", len(df), group_cols[0])
    else:
        kpi[1].metric("数据期间", f"{resp.get('date_start')} ~ {resp.get('date_end')}")

    if "环比 %" in df.columns and group_cols and len(df):
        worst = df.loc[df["环比 %"].idxmin()]
        kpi[2].metric("环比降幅最大", str(worst[group_cols[0]]), f"{worst['环比 %']:.2f}%")
    else:
        kpi[2].metric("数据集版本", resp.get("dataset_version", "-"))

    st.markdown("**查询结果**")
    st.dataframe(df, hide_index=True)

    if group_cols and num_cols:
        chart_df = df[group_cols + num_cols].set_index(group_cols[0])
        st.bar_chart(chart_df)
    elif num_cols:
        st.caption(f"{metric_label} = {df[num_cols[0]].iloc[0]:,.2f}")


def render_query_zone() -> None:
    st.subheader("智能取数区")
    st.caption("对应分工文档 §5.2.2「智能取数区」与 §5.2.1 的第 4~7 步。")

    # 第 3 步确认状态的温和提醒（不阻断查询；与业务字典区的承诺一致）
    n_confirmed = len(st.session_state.get("confirmed_metrics") or ())
    n_total = len(METRIC_SPEC)
    if n_confirmed == 0:
        st.info(
            "你尚未在「② 业务字典」确认任何指标口径。可以直接提问，"
            "但建议先核对口径 —— 口径理解不一致是取数结果互相矛盾的最常见原因。"
        )
    elif n_confirmed < n_total:
        st.caption(f"已确认 {n_confirmed} / {n_total} 个指标口径，"
                   "可在「② 业务字典」继续核对。")

    queries = [resp for resp in st.session_state["history"] if resp.get("status") == Status.SUCCESS]
    c1, c2 = st.columns([1, 3])
    c1.metric("已完成查询", len(queries))

    with st.form("ask", clear_on_submit=True):
        q = st.text_input(
            "用自然语言提问",
            placeholder="例如：2026年9月各地区的净销售额",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("提问")

    st.caption("快捷示例（点击即提问，同时作为接口自测用例）")
    cols = st.columns(5)
    for i, (kind, question, expect) in enumerate(PRESET_EXAMPLES):
        if cols[i % 5].button(question[:12] + "…", key=f"preset_{i}", help=f"{kind}｜预期状态：{STATUS_LABEL[expect]}\n{question}"):
            _show_skeleton()
            _submit(question)
            st.rerun()

    if submitted and q.strip():
        _show_skeleton()
        _submit(q.strip())
        st.rerun()

    if st.session_state["chat_log"]:
        st.markdown("**对话记录**")
        for turn in st.session_state["chat_log"]:
            with st.chat_message("user" if turn["role"] == "user" else "assistant"):
                st.write(turn["text"])

    clr = st.session_state.get("pending_clarification")
    if clr:
        st.divider()
        round_no = int(clr.get("round", 1))
        remaining = max(0, MAX_CLARIFICATION_ROUNDS - round_no)
        round_hint = (
            f"第 {round_no} / {MAX_CLARIFICATION_ROUNDS} 轮（这是最后一轮，"
            "若仍无法确定，将降级为「数据不足」而不是猜测一个答案）"
            if remaining == 0
            else f"第 {round_no} / {MAX_CLARIFICATION_ROUNDS} 轮（还剩 {remaining} 次机会）"
        )
        st.warning(
            f"**需要你补充信息**｜{REASON_LABEL.get(clr.get('reason_code'), clr.get('reason_code'))}"
            f"（{round_hint}）\n\n{clr['question']}"
        )
        options = clr.get("options") or []
        if options:
            labels = [f"{o['label']} —— {o.get('definition', '')}" for o in options]
            picked = st.radio("请选择：", labels, key=f"clr_{clr['id']}")
            idx = labels.index(picked)
            if st.button("提交选择", key=f"clr_submit_{clr['id']}"):
                _show_skeleton()
                _submit_clarification(options[idx]["value"])
                st.rerun()
        if clr.get("allow_free_text"):
            free = st.text_input("或直接用文字说明", key=f"clr_free_{clr['id']}")
            if st.button("提交文字说明", key=f"clr_free_btn_{clr['id']}") and free.strip():
                _show_skeleton()
                _submit_clarification("", free_text=free.strip())
                st.rerun()

    resp = st.session_state.get("last_response")
    if resp:
        st.divider()
        _status_banner(resp)
        if resp.get("status") == Status.SUCCESS:
            _render_success(resp)
            st.caption("完整的口径、来源、版本与查询记录见「④ 结果依据」页。")
        if resp.get("warnings"):
            st.markdown("**数据质量警告**")
            for w in resp["warnings"]:
                {"error": st.error, "warning": st.warning, "info": st.info}[w["level"]](
                    f"{w['message']}\n\n可能影响：{w['impact']}"
                )


# ===========================================================================
# ④ 结果依据区
# ===========================================================================

def render_evidence_zone() -> None:
    st.subheader("结果依据区")
    st.caption(
        "对应分工文档 §5.2.2「结果依据区」与 §5.4 验收标准："
        "每次成功查询都必须能查看口径和来源。"
    )

    resp = st.session_state.get("last_response")
    if not resp:
        st.info("还没有查询记录。请先到「③ 智能取数」提一个问题。")
        return

    st.markdown(f"**查询编号**　`{resp.get('query_id', '-')}`")
    st.markdown(f"**状态**　{STATUS_LABEL.get(resp.get('status'), resp.get('status'))}　—　{resp.get('message', '')}")
    st.markdown(f"**执行时间**　{resp.get('executed_at', '-')}")

    if resp.get("status") != Status.SUCCESS:
        if resp.get("reason"):
            st.markdown(f"**原因码**　`{resp['reason']}`")
        if resp.get("missing"):
            st.markdown(f"**缺少的信息/数据**　{'、'.join(resp['missing'])}")
        if resp.get("suggestion"):
            st.markdown(f"**建议**　{resp['suggestion']}")
        st.divider()

    if resp.get("status") == Status.SUCCESS:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**所用指标口径**")
            st.write(f"{LABEL_MAP.get(resp['metric'], resp['metric'])}（`{resp['metric']}`）")
            st.caption(resp.get("definition", ""))
            st.markdown("**单位**")
            st.write(resp.get("unit", "-"))
            st.markdown("**来源表**")
            st.write("、".join(resp.get("source_tables", [])))
        with c2:
            st.markdown("**时间范围**")
            st.write(f"{resp.get('date_start')} ~ {resp.get('date_end')}")
            st.markdown("**分组维度**")
            gb = resp.get("group_by") or []
            st.write("、".join(DIMENSION_SPEC[g]["label"] for g in gb) if gb else "不分组（汇总值）")
            st.markdown("**筛选条件**")
            af = resp.get("applied_filters") or {}
            st.write("、".join(f"{DIMENSION_SPEC[k]['label']}={v}" for k, v in af.items()) if af else "无")
            st.markdown("**数据集版本**")
            st.code(resp.get("dataset_version", "-"), language="text")

        st.markdown("**数据质量警告**")
        if resp.get("warnings"):
            st.dataframe(pd.DataFrame(resp["warnings"]), hide_index=True)
        else:
            st.success("本次查询没有数据质量警告。")

        st.markdown("**查询记录（SQL）**")
        st.code(resp.get("generated_sql", "-- 未返回"), language="sql")
        st.caption(
            "该 SQL 由平台生成并执行，只允许读取 orders / refunds / customers 三张表，"
            "不包含任何写操作。"
        )

        if resp.get("plan"):
            with st.expander("查看结构化查询计划（成员 2 生成）"):
                st.json(resp["plan"])

    if st.session_state.get("history"):
        with st.expander(f"历史查询记录（{len(st.session_state['history'])} 条）"):
            st.dataframe(pd.DataFrame([{
                "查询编号": h.get("query_id"),
                "问题": h.get("message"),
                "状态": STATUS_LABEL.get(h.get("status"), h.get("status")),
                "指标": LABEL_MAP.get(h.get("metric"), h.get("metric", "-")),
                "时间范围": f"{h.get('date_start')} ~ {h.get('date_end')}",
                "行数": h.get("row_count", "-"),
            } for h in st.session_state["history"]]), hide_index=True)


# ===========================================================================
# ⑤ Agent 调用回放
# ===========================================================================

def render_agent_zone() -> None:
    st.subheader("其他 Agent 调用平台的结果")
    st.caption(
        "对应分工文档 §5.2.1 第 8 步、§4.2.6 示例运营 Agent。"
        "示例 Agent 由成员 2 开发，此处先展示页面侧的调用与结果呈现方式。"
    )

    if st.button("运行示例运营 Agent：生成 2026 年 9 月经营简报"):
        with st.spinner("Agent 正在调用可信取数接口…"):
            try:
                resp = _client.submit("2026年9月各地区的净销售额环比对比")
                st.session_state["agent_result"] = resp
            except client_mod.BackendError as exc:
                st.error(f"Agent 调用失败：{exc}")

    resp = st.session_state.get("agent_result")
    if not resp:
        st.info("尚未运行。点击上方按钮查看示例 Agent 的完整调用结果。")
        return

    st.markdown("**调用步骤**")
    st.markdown(
        "1. 接收任务：生成 2026 年 9 月经营简报\n"
        "2. 调用可信取数接口：`POST /agent/query`\n"
        "3. 取回各地区净销售额及环比\n"
        "4. 找出下降幅度最大的地区\n"
        "5. 形成简短经营分析\n"
        "6. 标明数据口径、来源与分析限制"
    )

    if resp.get("status") != Status.SUCCESS:
        _status_banner(resp)
        return

    df = pd.DataFrame(resp["data"]).rename(columns=LABEL_MAP)
    metric_label = LABEL_MAP.get(resp["metric"], resp["metric"])
    if "上一期" in df.columns:
        prev = pd.to_numeric(df["上一期"], errors="coerce")
        cur = pd.to_numeric(df[metric_label], errors="coerce")
        df["环比 %"] = ((cur - prev) / prev.replace(0, pd.NA) * 100).round(2)
    st.dataframe(df, hide_index=True)

    if "环比 %" in df.columns and len(df):
        worst = df.loc[df["环比 %"].idxmin()]
        dim_col = LABEL_MAP.get((resp.get("group_by") or ["region"])[0], "地区")
        st.markdown("**Agent 生成的经营分析**")
        mom = worst["环比 %"]
        trend = "下降" if mom < 0 else "增长"
        body = (
            f"2026 年 9 月，{worst[dim_col]}地区净销售额为 {worst[metric_label]:,.2f} 元，"
            f"环比{trend} {abs(mom):.2f}%，为各地区中变化幅度最大。"
            if mom < 0 else
            f"2026 年 9 月，{worst[dim_col]}地区净销售额环比变化最小。"
        )
        st.write(body)
        st.markdown("**分析依据**")
        st.markdown(
            f"- 指标口径：{resp.get('definition')}\n"
            f"- 单位：{resp.get('unit')}\n"
            f"- 时间范围：{resp.get('date_start')} ~ {resp.get('date_end')}\n"
            f"- 来源表：{'、'.join(resp.get('source_tables', []))}\n"
            f"- 数据集版本：{resp.get('dataset_version')}\n"
            f"- 查询编号：{resp.get('query_id')}"
        )
        st.markdown("**分析限制**")
        st.markdown(
            "- 现有数据只能反映结果指标的变化，缺少营销活动、价格调整、竞品等外部变量，"
            "无法判断变化的**原因**。\n"
            "- 数据为模拟业务数据，结论仅用于验证流程，不代表真实经营情况。\n"
            "- 环比对比期已按上一自然月对齐。"
        )
    st.markdown("**查询记录（SQL）**")
    st.code(resp.get("generated_sql", "-- 未返回"), language="sql")


# ===========================================================================
# 渲染
# ===========================================================================

with tab_data:
    _tables = render_data_zone()
    _client.set_tables(_tables)

with tab_dict:
    render_dictionary_zone()

with tab_query:
    render_query_zone()

with tab_evidence:
    render_evidence_zone()

with tab_agent:
    render_agent_zone()
