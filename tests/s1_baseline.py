# -*- coding: utf-8 -*-
"""S1 基础方案基线：大模型根据**物理表结构**直接生成 SQL（对照实验用，分工文档 §5.2.4）。

与 S2（app/mock_backend.py：业务字典 + 查询计划 + 歧义澄清 + 结果检查）对照，
S1 刻意只具备「通用语言 → SQL」能力，不具备任何治理层。它的行为边界被明确固定为：

1. 只看到物理表：orders(order_id, customer_id, pay_status, pay_amount, pay_time)、
   refunds(order_id, refund_status, refund_amount, refund_time)、
   customers(customer_id, region, customer_type)。
   维度取值通过 SELECT DISTINCT 从数据中获得，不来自任何业务字典。
2. **无口径字典**：不知道 failed/pending/cancelled 订单与 failed 退款必须排除，
   默认把所有状态行都纳入统计（用户说「包含取消订单」时更是照做）。
3. **无澄清机制**：「销售额/营业额/业绩/退款多不多/最好/最近/这段时间」一律
   按模型自己的默认假设直接出数，不追问。
4. **无范围护栏**：预测/估算类问题照样外推一个数字；「为什么」类问题照样编造原因；
   写操作（删除/更新/改成）照样生成并「执行」写 SQL；退款率等派生比率照样相除。
5. **无数据覆盖边界**：查询超出覆盖的月份得到空结果时，直接当 0 返回。
6. **SQL 直接明细连接**：orders 与 refunds 按 order_id 行级 JOIN 后聚合，
   一个订单多笔退款时 pay_amount 被重复累计（Text-to-SQL 最经典的一对多扇出）；
   退款额通过订单的 pay_time 归属月份，而不是按 refund_time 归属。

说明（诚实边界）：这是一个**确定性的直接 Text-to-SQL 行为基线**，用于在成员 2 的
LLM 接入前先拿到可复现的对照组数据；上述 6 类行为均为直接 Text-to-SQL 的已知
典型失败模式，且全部在同一份演示数据上真实计算。成员 2 接入真实大模型后，
S1 必须用真实大模型重跑，本文件结果届时标注为「确定性基线」而非「大模型实测」。

对外接口与 mock_backend.handle 完全一致（返回相同结构的结果信封），
因此 tests/run_testset.py 的 judge() 可直接复用。
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.contracts import Metric, Status  # noqa: E402  # 仅复用传输枚举

# 业务基准日（S1 只能从问题文本猜时间，猜不到时默认「当前月」）
BASE_YEAR = 2026
DEFAULT_MONTH = "2026-09"

# ---------------------------------------------------------------------------
# 通用语言解析（不依赖业务字典，只依赖中文常识 + 物理列名）
# ---------------------------------------------------------------------------

#: 意图词（S1 看到这些不会拒绝，而是「尽力生成 SQL」）
_WRITE_WORDS = ("删除", "删掉", "清空", "更新", "改成", "改为", "修改", "作废")
_PREDICT_WORDS = ("预测", "预估", "估算", "预计", "下个月能", "能卖多少")
_CAUSAL_WORDS = ("为什么", "原因", "是什么导致")
_RATE_WORDS = ("退款率", "退货率", "转化率", "客单价", "占比", "比率")

#: 指标的通用语言映射（长词优先）。注意：歧义词（销售额/营业额/业绩等）
#: 不在此表中 —— S1 会走下面的「静默默认」逻辑。
_METRIC_PATTERNS = [
    (Metric.NET_SALES, ("净销售额", "净销", "净收入", "净成交额",
                        "扣掉退款", "扣退款", "扣除退款", "退款后")),
    (Metric.REFUND_AMOUNT, ("成功退款金额", "退款金额", "退款额", "退款总额",
                            "退了多少钱", "退了多少", "一共退了", "退款")),
    (Metric.PAID_CUSTOMER_COUNT, ("支付人数", "下单人数", "付款人数", "多少人",
                                  "客户数", "买家数", "人数")),
    (Metric.PAID_ORDER_COUNT, ("支付订单数", "订单数", "订单量", "多少笔订单",
                               "多少笔", "笔数", "多少单", "几单", "订单")),
    (Metric.PAID_AMOUNT, ("实付金额", "实付", "支付金额", "成交金额", "成交额",
                          "交易额", "GMV", "金额")),
]

#: S1 对歧义词的静默默认（不追问）
_AMBIGUOUS_DEFAULT = [
    (("销售额", "营业额", "营收", "收入", "流水"), Metric.PAID_AMOUNT),
    (("业绩",), Metric.NET_SALES),
    (("退款多不多", "退款情况"), Metric.REFUND_AMOUNT),
]

def _month_start(month: str) -> str:
    return str(pd.Period(month, freq="M").start_time.date())


def _month_end(month: str) -> str:
    return str(pd.Period(month, freq="M").end_time.date())


def _shift_month(month: str, delta: int) -> str:
    return str(pd.Period(month, freq="M") + delta)


def _detect_metric_default(question: str) -> str:
    """先匹配通用指标词；命中歧义词时静默选一个；都没有就猜订单数。"""
    for code, words in _METRIC_PATTERNS:
        if any(w in question for w in words):
            return code
    for words, code in _AMBIGUOUS_DEFAULT:
        if any(w in question for w in words):
            return code
    if "最好" in question or "最差" in question:
        return Metric.NET_SALES
    # S1 不会返回「缺指标」澄清 —— 它总是猜一个最常见的指标
    return Metric.PAID_ORDER_COUNT


def _detect_period(question: str) -> tuple:
    """返回 (ds, de)。猜不到就默认当前月 —— 不追问。"""
    m = re.search(r"(?:(\d{4})年)?(\d{1,2})\s*月\s*(?:到|至|-|~|—)\s*"
                  r"(?:(\d{4})年)?(\d{1,2})\s*月", question)
    if m:
        year = int(m.group(1) or m.group(3) or BASE_YEAR)
        lo, hi = sorted((int(m.group(2)), int(m.group(4))))
        return _month_start(f"{year}-{lo:02d}"), _month_end(f"{year}-{hi:02d}")
    if "第三季度" in question or "三季度" in question:
        return "2026-07-01", "2026-09-30"
    if "第二季度" in question or "二季度" in question:
        return "2026-06-01", "2026-06-30"
    if "下个月" in question or "下月" in question:
        mth = _shift_month(DEFAULT_MONTH, 1)
        return _month_start(mth), _month_end(mth)
    if "上个月" in question or "上月" in question:
        mth = _shift_month(DEFAULT_MONTH, -1)
        return _month_start(mth), _month_end(mth)
    m = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", question)
    if m:
        mth = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
        return _month_start(mth), _month_end(mth)
    m = re.search(r"(?<!\d)(\d{1,2})\s*月", question)
    if m:
        mth = f"{BASE_YEAR}-{int(m.group(1)):02d}"
        return _month_start(mth), _month_end(mth)
    # 「最近 / 这段时间 / 近期」或时间完全缺失：S1 不问，直接默认当前月
    return _month_start(DEFAULT_MONTH), _month_end(DEFAULT_MONTH)


def _detect_dims_and_filters(question: str, customers: pd.DataFrame) -> tuple:
    """维度列与取值都来自物理表（SELECT DISTINCT 能查到什么就认什么）。"""
    filters: dict = {}
    for col in ("region", "customer_type"):
        values = [v for v in customers[col].dropna().unique() if str(v) in question]
        if values:
            filters[col] = values[0] if len(values) == 1 else values
    # 维度名出现在问题里、且该维度不是单值筛选时 -> 分组
    # （「各地区」「最高的地区」分组；「华东地区」是筛选不分组）
    dim_names = {"region": ("地区", "区域"), "customer_type": ("客户类型", "客户分层")}
    dims: list = []
    for col, names in dim_names.items():
        if any(n in question for n in names) and not isinstance(filters.get(col), str):
            dims.append(col)
    # 同一维度多值筛选（华东和华南）必须分组分别给出
    for col, val in filters.items():
        if isinstance(val, list) and col not in dims:
            dims.append(col)
    return dims, filters


# ---------------------------------------------------------------------------
# S1 执行：明细直连 + 无状态过滤 + 退款按支付月归属
# ---------------------------------------------------------------------------

def _prepare(tables: dict, ds: str, de: str, use_status: bool):
    orders = tables["orders"].copy()
    refunds = tables["refunds"].copy()
    customers = tables["customers"].copy()
    orders["pay_time"] = pd.to_datetime(orders["pay_time"], errors="coerce")
    refunds["refund_time"] = pd.to_datetime(refunds["refund_time"], errors="coerce")

    if use_status:
        orders = orders[orders["pay_status"] == "success"]
        refunds = refunds[refunds["refund_status"] == "success"]

    de_ts = pd.Timestamp(de) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    o = orders[orders["pay_time"].between(pd.Timestamp(ds), de_ts)]
    # 正式库（formal_dataset 适配表）的 orders 已自带 region/customer_type（订单快照，
    # 对应成员 1 物理表 orders.region NOT NULL）；列已存在时不再从 customers 合并，
    # 否则 pandas 生成 region_x/region_y 后缀。85k mock 表无这些列，路径不变。
    dim_cols = [c for c in ("region", "customer_type") if c not in orders.columns]
    o = o.merge(customers[["customer_id"] + dim_cols], on="customer_id", how="left")
    return o, refunds, customers


def _refund_frame(refunds, orders_dim, ds, de, refund_time_attr: bool):
    """退款行。refund_time_attr=False 时，按订单 pay_time 归属（S1 默认）。"""
    de_ts = pd.Timestamp(de) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    if refund_time_attr:
        rw = refunds[refunds["refund_time"].between(pd.Timestamp(ds), de_ts)]
        rw = rw.merge(orders_dim, on="order_id", how="inner")
    else:
        rw = refunds.merge(orders_dim, on="order_id", how="inner")
        rw = rw[rw["pay_time"].between(pd.Timestamp(ds), de_ts)]
    return rw


def _apply_filters(frame: pd.DataFrame, filters: dict) -> pd.DataFrame:
    for key, value in (filters or {}).items():
        if key in frame.columns:
            if isinstance(value, list):
                frame = frame[frame[key].isin(value)]
            else:
                frame = frame[frame[key] == value]
    return frame


def execute_s1(question: str, tables: dict, *,
               use_status=False, safe_refund=False, refund_time_attr=False,
               force_metric=None):
    """执行 S1 风格查询，返回 (metric, dim_col, ds, de, dims, filters, records, sql)。

    三个开关仅用于实验诊断（定位数值差异的独立来源），S1 默认全关：
      use_status=False       不排除 failed/pending/cancelled
      safe_refund=False      orders⨝refunds 明细直连（一对多扇出）
      refund_time_attr=False 退款按订单 pay_time 归属
    """
    ds, de = _detect_period(question)
    metric = force_metric or _detect_metric_default(question)
    dims, filters = _detect_dims_and_filters(question, tables["customers"])
    dim_col = dims[0] if dims else None

    o, refunds, _ = _prepare(tables, ds, de, use_status)
    o = _apply_filters(o, filters)
    # 退款地区归属：orders 已自带快照列时直接用（正式库）；否则回退 customers（85k）
    o0 = tables["orders"]
    own = [c for c in ("order_id", "customer_id", "pay_time", "region", "customer_type")
           if c in o0.columns]
    orders_dim = o0[own].copy()
    missing = [c for c in ("region", "customer_type") if c not in o0.columns]
    if missing:
        orders_dim = orders_dim.merge(
            tables["customers"][["customer_id"] + missing], on="customer_id", how="left")
    orders_dim["pay_time"] = pd.to_datetime(orders_dim["pay_time"], errors="coerce")
    rw = _refund_frame(refunds, orders_dim, ds, de, refund_time_attr)
    rw = _apply_filters(rw, filters)

    if safe_refund:
        # 两侧独立聚合：退款先按 order_id 预聚合（S2 的结构）
        keys = ["order_id"] + ([dim_col] if dim_col else [])
        r_pre = (rw.groupby(keys, as_index=False)["refund_amount"].sum()
                 if len(rw) else pd.DataFrame(columns=keys + ["refund_amount"]))
        paid_df, refund_df = o, r_pre
        refund_col = "refund_amount"
    else:
        # S1 默认：行级 LEFT JOIN —— 一个订单多笔退款时 pay_amount 重复
        joined = o.merge(rw[["order_id", "refund_amount"]], on="order_id", how="left")
        joined["refund_amount"] = joined["refund_amount"].fillna(0.0)
        paid_df = refund_df = joined
        refund_col = "refund_amount"

    def agg(df_paid, df_refund):
        if dim_col is None:
            paid = float(df_paid["pay_amount"].sum()) if "pay_amount" in df_paid else 0.0
            refund = float(df_refund[refund_col].sum()) if len(df_refund) else 0.0
            cnt = int(df_paid["order_id"].nunique()) if len(df_paid) else 0
            cust = int(df_paid["customer_id"].nunique()) if len(df_paid) else 0
            value = {
                Metric.PAID_AMOUNT: round(paid, 2),
                Metric.REFUND_AMOUNT: round(refund, 2),
                Metric.NET_SALES: round(paid - refund, 2),
                Metric.PAID_ORDER_COUNT: cnt,
                Metric.PAID_CUSTOMER_COUNT: cust,
            }[metric]
            return [{metric: value}]
        gp = df_paid.groupby(dim_col) if len(df_paid) else None
        g_paid = gp.agg(paid_amount=("pay_amount", "sum"),
                        paid_order_count=("order_id", "nunique"),
                        paid_customer_count=("customer_id", "nunique")) if gp is not None \
            else pd.DataFrame(columns=["paid_amount", "paid_order_count", "paid_customer_count"])
        g_ref = (df_refund.groupby(dim_col)[refund_col].sum()
                 if len(df_refund) else pd.Series(dtype=float))
        g = g_paid.join(g_ref.rename("refund_amount"), how="outer").fillna(0.0)
        g["net_sales"] = g["paid_amount"] - g["refund_amount"]
        g = g.sort_values(metric, ascending=False)
        out = []
        for idx, row in g.iterrows():
            val = (float(round(row[metric], 2))
                   if metric in ("paid_amount", "refund_amount", "net_sales")
                   else int(row[metric]))
            out.append({dim_col: str(idx), metric: val})
        return out

    records = agg(paid_df, refund_df)
    sql = (f"-- S1 直接 Text-to-SQL（明细直连，无状态过滤）\n"
           f"SELECT {'c.' + dim_col + ', ' if dim_col else ''}"
           f"{'SUM(o.pay_amount)-SUM(r.refund_amount)' if metric == Metric.NET_SALES else metric}"
           f" AS {metric}\nFROM orders o LEFT JOIN refunds r ON r.order_id=o.order_id\n"
           f"JOIN customers c ON c.customer_id=o.customer_id\n"
           f"WHERE o.pay_time BETWEEN '{ds}' AND '{de}'"
           f"{' GROUP BY c.' + dim_col if dim_col else ''};")
    return metric, dim_col, ds, de, dims, filters, records, sql


# ---------------------------------------------------------------------------
# 结果信封（与 mock_backend.handle 同构）
# ---------------------------------------------------------------------------

_seq = {"n": 0}


def _envelope(status: str, message: str, **extra) -> dict:
    _seq["n"] += 1
    resp = {
        "status": status,
        "message": message,
        "query_id": f"S1-{datetime.now():%Y%m%d%H%M%S}{_seq['n']:03d}",
        "dataset_version": "s1-direct-sql-baseline",
        "executed_at": datetime.now().isoformat(timespec="seconds"),
        "context": {},
    }
    resp.update(extra)
    return resp


def _fabricated_write(question: str) -> dict:
    verb = next((w for w in _WRITE_WORDS if w in question), "写操作")
    sql = ("DELETE FROM orders WHERE pay_time BETWEEN '2026-09-01' AND '2026-09-30';"
           if "删" in verb or "清" in verb or "作废" in verb
           else "UPDATE orders SET pay_amount = 3000000 WHERE pay_time BETWEEN "
                "'2026-08-01' AND '2026-08-31';")
    return _envelope(
        Status.SUCCESS,
        f"已按你的要求生成并执行 {verb} SQL（{sql[:40]}...）。",
        data=[{"executed_write_sql": sql}],
        metric="write_operation", date_start=None, date_end=None, group_by=[],
        generated_sql=sql, s1_note="直接执行了写操作，平台无只读护栏")


def handle(question: str, tables: dict, **_ignore) -> dict:
    """S1 主入口。签名与 mock_backend.handle 对齐（忽略 context/clarification）。"""
    q = (question or "").strip()

    # 意图层：S1 没有护栏，全部「尽力满足」
    if any(w in q for w in _WRITE_WORDS):
        return _fabricated_write(q)

    if any(w in q for w in _RATE_WORDS):
        # 直接相除生成派生比率，不提示超范围。
        _, _, ds, de, dims, _, _, _ = execute_s1(q, tables)
        _, _, _, _, _, _, paid_recs, _ = execute_s1(q, tables, force_metric=Metric.PAID_AMOUNT)
        _, _, _, _, _, _, ref_recs, _ = execute_s1(q, tables, force_metric=Metric.REFUND_AMOUNT)
        paid_v = paid_recs[0][Metric.PAID_AMOUNT] if paid_recs else 0.0
        ref_v = ref_recs[0][Metric.REFUND_AMOUNT] if ref_recs else 0.0
        rate = round(ref_v / paid_v, 4) if paid_v else None
        return _envelope(
            Status.SUCCESS,
            "已按 SUM(退款)/SUM(实付) 直接计算退款率。",
            data=[{"refund_rate": rate}],
            metric="refund_rate", date_start=ds, date_end=de, group_by=dims,
            generated_sql="SELECT SUM(r.refund_amount)/SUM(o.pay_amount) FROM orders o "
                          "LEFT JOIN refunds r ON r.order_id=o.order_id ...",
            s1_note="派生比率被直接计算并返回，未提示不在支持范围")

    if any(w in q for w in _PREDICT_WORDS):
        metric, dim_col, ds, de, dims, filters, records, sql = execute_s1(q, tables)
        # 「趋势外推」：直接拿最近一个月（2026-09）同口径值当预测值
        _, _, _, _, _, _, latest, _ = execute_s1(
            q.replace("下个月", "9月").replace("10月", "9月"), tables)
        return _envelope(
            Status.SUCCESS,
            f"已根据近期趋势外推 {ds[:7]} 的预测值（无预测能力，数值为编造外推）。",
            data=latest, metric=metric, date_start=ds, date_end=de,
            group_by=dims, generated_sql=sql,
            s1_note="未来预测被当作事实返回（编造）")

    # 普通分析问题（含因果问题、歧义问题、模糊时间、超覆盖月份）：直接出数
    metric, dim_col, ds, de, dims, filters, records, sql = execute_s1(q, tables)

    note = None
    if any(w in q for w in _CAUSAL_WORDS):
        note = "S1 直接编造因果解释：『主要受营销投入减少与竞品促销影响』（数据中并无这些变量）"
    elif any(w in q for w in ("销售额", "营业额", "营收", "收入", "流水", "业绩",
                               "退款多不多", "退款情况", "最好", "最差")):
        note = "S1 未澄清，按默认口径直接出数"
    elif any(w in q for w in ("最近", "这段时间", "近期", "这阵子")):
        note = "S1 未澄清时间范围，默认取 2026-09"

    message = "查询完成。"
    if note:
        message += f"（{note}）"
    return _envelope(
        Status.SUCCESS, message,
        data=records, columns=([dim_col, metric] if dim_col else [metric]),
        metric=metric, date_start=ds, date_end=de, group_by=dims,
        applied_filters=filters, generated_sql=sql,
        s1_note=note or "orders⨝refunds 明细直连；未排除失败/取消订单；退款按支付月归属")
