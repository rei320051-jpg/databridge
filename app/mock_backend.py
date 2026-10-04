# -*- coding: utf-8 -*-
"""模拟后端：成员 2（问题解析/澄清）+ 成员 1（查询执行）的页面侧参考实现。

用途（三点，缺一不可）：
1. 让成员 3 的页面在接口未就绪时即可跑通全流程（含澄清分支）；
2. 作为成员 1 / 成员 2 接口的**行为基准**，字段与状态取值全部来自 shared/contracts.py；
3. 作为成员 3 的**对照实现**，用于交叉验证成员 1 返回的数值是否一致。

它不是最终后端，最终查询服务由成员 1 交付。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.contracts import (  # noqa: E402
    ALLOWED_FILTER_KEYS,
    AMBIGUOUS_METRIC_TERMS,
    CURRENCY_UNIT,
    DATASET_COVERAGE,
    DATASET_VERSION,
    DIMENSION_SPEC,
    MAX_CLARIFICATION_ROUNDS,
    METRIC_SPEC,
    Metric,
    REASON_LABEL,
    ReasonCode,
    Status,
    clarification_id,
    clarification_field,
)

_QUERY_SEQ = {"n": 0}


# ---------------------------------------------------------------------------
# 词表
# ---------------------------------------------------------------------------

WRITE_WORDS = ("删除", "删掉", "清空", "作废", "修改", "更改", "更新", "移除",
               "插入", "新增数据", "写入", "覆盖", "改一下", "改成", "改为",
               "调整成", "导回", "drop", "delete", "update", "insert", "truncate")

#: 口径冲突标记：用户要求按指标字典**未定义**的口径计算。
#: 这类问题不能默默返回一个标准口径的数字——那正是错误数字被当成正确结论的典型场景。
CONFLICT_PHRASES = (
    "包含取消", "含取消", "包括取消", "把取消", "算上取消",
    "包含失败", "含失败", "算上失败", "包括失败", "把失败也算",
    "含未支付", "包含未支付", "未支付成功", "含待支付", "包含待支付",
    "所有订单", "不计入退款", "不扣退款", "不扣减退款",
)

#: 仍不支持的比率类词（v1.2 起退款率/客单价/人均消费已支持，从拒答词表移除；
#: 复购率按 DM-006 继续拒答）
RATE_WORDS = ("退货率", "转化率", "占比", "百分比", "比率",
              "复购率", "同比增速", "增长率", "毛利率", "净利率")

FUTURE_WORDS = ("预测", "预估", "推算", "估算", "估计", "预计", "下个月会",
                "明年", "未来", "将会", "会不会涨", "趋势外推", "展望", "能卖多少")

CAUSAL_WORDS = ("为什么", "原因", "导致", "是因为", "什么造成", "归因",
                "怎么会", "什么因素", "影响因素")

CRITERION_WORDS = ("最好", "最差", "最强", "表现最", "哪个地区好", "哪个好", "最优")

SORT_DESC_WORDS = ("最高", "最多", "最大", "最好", "排名", "排行", "前五", "前几",
                   "top", "降幅最大", "下降最多", "下降最大", "下跌最多")
SORT_ASC_WORDS = ("最低", "最少", "最小", "最差")

GROUP_MARKERS = ("各", "每个", "分", "按", "分别", "排名", "排行", "哪个", "哪些", "对比", "top")

CN_MONTH = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
            "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _new_query_id() -> str:
    _QUERY_SEQ["n"] += 1
    return f"Q{datetime.now():%Y%m%d%H%M%S}{_QUERY_SEQ['n']:03d}"


def _envelope(status: str, message: str, dataset_version: str | None = None,
             **extra) -> dict:
    resp = {
        "status": status,
        "message": message,
        "query_id": _new_query_id(),
        "dataset_version": dataset_version or DATASET_VERSION,
        "executed_at": datetime.now().isoformat(timespec="seconds"),
        "context": {},
    }
    resp.update(extra)
    return resp


def _month_end(month: str) -> str:
    return str(pd.Period(month, freq="M").end_time.date())


def _month_start(month: str) -> str:
    return str(pd.Period(month, freq="M").start_time.date())


def _shift_month(month: str, delta: int) -> str:
    return str(pd.Period(month, freq="M") + delta)


def _months_between(ds: str, de: str) -> list:
    return [str(p) for p in pd.period_range(pd.Timestamp(ds), pd.Timestamp(de), freq="M")]


def _looks_like_month(s: str) -> bool:
    return bool(__import__("re").fullmatch(r"\d{4}-\d{2}", s or ""))


# ---------------------------------------------------------------------------
# 解析：拒答判断
# ---------------------------------------------------------------------------

def _reject(question: str):
    low = question.lower()
    if any(w in low for w in WRITE_WORDS):
        return (Status.OUT_OF_SCOPE, "写操作不支持", "write_operation_refused",
                ["写操作能力"],
                "数桥是只读取数平台，不提供任何数据修改能力。请改用查询类问题。", False)
    if any(w in question for w in RATE_WORDS):
        return (Status.OUT_OF_SCOPE, "该派生比率指标不在首版范围", "derived_metric_unsupported",
                ["派生指标定义"],
                "首版支持 5 个基础指标（支付订单数、支付人数、实付金额、成功退款金额、净销售额）"
                "与 3 个派生指标（退款率、客单价、支付人均消费）。复购率、转化率、毛利率等"
                "暂不支持，请改查已支持的指标或其分子、分母。", False)
    if any(w in question for w in FUTURE_WORDS):
        return (Status.OUT_OF_SCOPE, "不支持预测未来", "no_forecast_capability",
                ["时序预测能力", "未来期间数据"],
                "平台只查询历史已发生的数据。预测属于建模能力，不在本产品范围内。", False)
    if any(w in question for w in CAUSAL_WORDS):
        return (Status.INSUFFICIENT_DATA, "无法支持因果判断", "causal_reasoning_unsupported",
                ["营销活动数据", "竞品数据", "价格调整记录", "库存与履约数据"],
                "现有数据只能反映结果指标的变化，缺少活动、价格、竞品等外部变量，"
                "无法判断下降原因。可以改为查询「华东地区各月净销售额」观察变化幅度。", False)
    return None


# ---------------------------------------------------------------------------
# 解析：指标 / 时间 / 维度 / 筛选 / 排序
# ---------------------------------------------------------------------------

def _detect_metric(question: str, context: dict):
    if context.get("metric"):
        return "ok", context["metric"]

    # 显式指标优先：同义词越长越具体，必须先匹配
    ranked = sorted(
        METRIC_SPEC.items(),
        key=lambda kv: -max(len(s) for s in kv[1]["synonyms"]),
    )
    for code, spec in ranked:
        for syn in sorted(spec["synonyms"], key=len, reverse=True):
            if syn in question:
                return "ok", code

    for term in sorted(AMBIGUOUS_METRIC_TERMS, key=len, reverse=True):
        if term in question:
            return "ambiguous", AMBIGUOUS_METRIC_TERMS[term]

    return "missing", None


def _coverage(coverage_months: list | None) -> dict:
    """生效的数据覆盖区间。默认取契约常量；正式联调库可显式传入其元数据区间。

    覆盖范围必须来自显式元数据，不能按数据最早/最晚交易推断（成员 1 数据字典规则）。
    """
    if not coverage_months:
        return DATASET_COVERAGE
    return {"months": list(coverage_months),
            "start": f"{coverage_months[0]}-01",
            "end": _month_end(coverage_months[-1])}


def _detect_period(question: str, context: dict, coverage_months: list | None = None):
    import re

    cov = _coverage(coverage_months)

    if context.get("date_start") and context.get("date_end"):
        return "ok", context["date_start"], context["date_end"]

    m = re.search(r"(20\d{2})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})", question)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return "ok", f"{y:04d}-{mo:02d}-{d:02d}", f"{y:04d}-{mo:02d}-{d:02d}"

    # 显式区间：「6月到8月」「2026年7月-9月」
    m_rng = re.search(
        r"(?:(\d{4})年)?(\d{1,2})\s*月\s*(?:到|至|-|~|—)\s*(?:(\d{4})年)?(\d{1,2})\s*月",
        question)
    if m_rng:
        year = int(m_rng.group(1) or m_rng.group(3) or 2026)
        a, b = int(m_rng.group(2)), int(m_rng.group(4))
        lo, hi = min(a, b), max(a, b)
        start_m, end_m = f"{year:04d}-{lo:02d}", f"{year:04d}-{hi:02d}"
        ds_r, de_r = _month_start(start_m), _month_end(end_m)
        if ds_r >= cov["start"] and de_r <= cov["end"]:
            return "ok", ds_r, de_r
        return "out_of_coverage", ds_r, de_r

    if any(k in question for k in ("第三季度", "三季度", "Q3", "q3")):
        return "ok", "2026-07-01", "2026-09-30"
    if any(k in question for k in ("第二季度", "二季度", "Q2", "q2")):
        return "ok", "2026-06-01", "2026-06-30"
    if any(k in question for k in ("上个月", "上月", "前一个月")):
        mm = _shift_month("2026-09", -1)
        return "ok", _month_start(mm), _month_end(mm)
    if any(k in question for k in ("本月", "这个月", "当月", "当月")):
        return "ok", _month_start("2026-09"), _month_end("2026-09")
    if any(k in question for k in ("近30天", "最近30天", "过去30天", "近一个月")):
        return "ok", "2026-09-01", "2026-09-30"

    m = re.search(r"(?<!\d)(\d{1,2})\s*月", question)
    month_no = None
    if m:
        month_no = int(m.group(1))
    else:
        m2 = re.search(r"([一二三四五六七八九十]{1,2})\s*月", question)
        if m2 and "季度" not in question:
            month_no = CN_MONTH.get(m2.group(1))
    if month_no and 1 <= month_no <= 12:
        mm = f"2026-{month_no:02d}"
        if mm in cov["months"]:
            return "ok", _month_start(mm), _month_end(mm)
        return "out_of_coverage", _month_start(mm), _month_end(mm)

    if any(k in question for k in ("最近", "近期", "这段时间", "这阵子", "近来")):
        return "ambiguous", None, None

    return "missing", None, None


def _detect_group_by(question: str, context: dict):
    if context.get("group_by") is not None:
        return list(context["group_by"])

    has_marker = any(k in question for k in GROUP_MARKERS)
    dims = []
    for code, spec in DIMENSION_SPEC.items():
        if any(s in question for s in spec["synonyms"]):
            dims.append(code)

    # 出现了维度的具体取值（如「华东」）且没有分组标记 -> 视为筛选，不是分组
    filters = _detect_filters(question, context)
    if not has_marker:
        dims = [d for d in dims if d not in filters]
    # 同一维度出现多个取值时，必须按该维度分组分别给出，而不是求和或只返回一个
    for code, value in filters.items():
        if isinstance(value, (list, tuple)) and code not in dims:
            dims.append(code)
    return dims


def _detect_filters(question: str, context: dict) -> dict:
    """识别同一维度的**所有**取值。

    单个取值 -> 标量；多个取值 -> 数组，表示「这两个地区分别是多少」，
    必须分别给出，不能求和，也不能只返回其中一个。
    """
    f: dict = {}
    for code, spec in DIMENSION_SPEC.items():
        hits = [v for v in spec["values"] if v in question]
        if len(hits) == 1:
            f[code] = hits[0]
        elif len(hits) > 1:
            f[code] = hits
    for k, v in (context.get("filters") or {}).items():
        if k in ALLOWED_FILTER_KEYS and k not in f:
            f[k] = v
    return f


def _detect_sort(question: str) -> str:
    low = question.lower()
    if any(w in low for w in SORT_ASC_WORDS):
        return "asc"
    if any(w in low for w in SORT_DESC_WORDS):
        return "desc"
    return "desc"


def _detect_comparison(question: str) -> str:
    if any(k in question for k in ("环比", "对比上月", "跟上月比", "和上月比", "下降最多", "降幅最大")):
        return "mom"
    return "none"


# ---------------------------------------------------------------------------
# 澄清构造
# ---------------------------------------------------------------------------

def _build_clarification(target_field: str, reason_code: str, question: str,
                         options: list, resolved_context: dict, allow_free_text=True) -> dict:
    return {
        "id": clarification_id(target_field, 1),
        "target_field": target_field,
        "reason_code": reason_code,
        "question": question,
        "options": options,
        "allow_free_text": allow_free_text,
        "resolved_context": resolved_context,
        "round": int(resolved_context.get("clarification_round", 0)) + 1,
    }


def _metric_options(codes: list) -> list:
    return [
        {"value": c, "label": METRIC_SPEC[c]["label"], "definition": METRIC_SPEC[c]["definition"]}
        for c in codes
    ]


def _normalize_choice(target_field: str, raw: str) -> str:
    """把用户选择（可能是编码，也可能是中文标签/同义词）归一成契约取值。"""
    if not raw:
        return raw
    raw = raw.strip()
    if target_field in ("metric", "criterion"):
        if raw in METRIC_SPEC:
            return raw
        for code, spec in METRIC_SPEC.items():
            if raw == spec["label"] or raw in spec["synonyms"]:
                return code
    if target_field == "group_by":
        if raw in DIMENSION_SPEC:
            return raw
        for code, spec in DIMENSION_SPEC.items():
            if raw == spec["label"] or raw in spec["synonyms"]:
                return code
    if target_field == "date_range" and _looks_like_month(raw):
        return raw
    return raw


# ---------------------------------------------------------------------------
# 查询执行（真正的 pandas 计算）
# ---------------------------------------------------------------------------

def _attach_dimensions(frame: pd.DataFrame, customers: pd.DataFrame) -> pd.DataFrame:
    """补 region / customer_type 维度。

    若订单行自带维度快照列（成员 1 正式库约定：地区为订单产生时快照，
    同一客户可跨地区下单），直接采用；否则回退到从 customers 关联
    （内置演示数据客户↔地区为 1:1，两种取法等价）。
    """
    dims = ["region", "customer_type"]
    missing = [d for d in dims if d not in frame.columns]
    if missing:
        frame = frame.merge(customers[["customer_id", *missing]],
                            on="customer_id", how="left")
    return frame


def _slice_period(tables: dict, ds: str, de: str):
    orders = tables["orders"].copy()
    refunds = tables["refunds"].copy()
    customers = tables["customers"].copy()

    ds_ts = pd.Timestamp(ds)
    de_ts = pd.Timestamp(de) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

    orders["pay_time"] = pd.to_datetime(orders["pay_time"], errors="coerce")
    o = orders[orders["pay_status"] == "success"]
    o = o[o["pay_time"].between(ds_ts, de_ts)]
    o = _attach_dimensions(o, customers)

    refunds["refund_time"] = pd.to_datetime(refunds["refund_time"], errors="coerce")
    r = refunds[refunds["refund_status"] == "success"]
    r = r[r["refund_time"].between(ds_ts, de_ts)]
    # 关键：先按 order_id 预聚合，避免一个订单多条退款导致实付金额重复累计
    r_agg = r.groupby("order_id", as_index=False)["refund_amount"].sum()
    # 退款的地区/客户类型继承原订单（订单快照），不从客户表现取，
    # 否则跨地区下单客户的退款会被归错地区
    order_dims = orders[["order_id", "customer_id", *[d for d in ("region", "customer_type")
                                                       if d in orders.columns]]]
    r_agg = r_agg.merge(order_dims, on="order_id", how="left")
    r_agg = _attach_dimensions(r_agg, customers)
    return o, r_agg


def _apply_filters(frame: pd.DataFrame, filters: dict) -> pd.DataFrame:
    for key, value in (filters or {}).items():
        if key in ALLOWED_FILTER_KEYS and key in frame.columns:
            if isinstance(value, (list, tuple)):
                frame = frame[frame[key].isin(list(value))]
            else:
                frame = frame[frame[key] == value]
    return frame


def _aggregate(o: pd.DataFrame, r_agg: pd.DataFrame, metric: str, dim_col):
    if dim_col is None:
        paid = float(o["pay_amount"].sum()) if len(o) else 0.0
        refund = float(r_agg["refund_amount"].sum()) if len(r_agg) else 0.0
        orders_cnt = int(o["order_id"].nunique()) if len(o) else 0
        cust_cnt = int(o["customer_id"].nunique()) if len(o) else 0
        value = {
            Metric.PAID_AMOUNT: paid,
            Metric.REFUND_AMOUNT: refund,
            Metric.NET_SALES: round(paid - refund, 2),
            Metric.PAID_ORDER_COUNT: orders_cnt,
            Metric.PAID_CUSTOMER_COUNT: cust_cnt,
        }[metric]
        return value

    g_o = o.groupby(dim_col).agg(
        paid_amount=("pay_amount", "sum"),
        paid_order_count=("order_id", "nunique"),
        paid_customer_count=("customer_id", "nunique"),
    ) if len(o) else pd.DataFrame(columns=["paid_amount", "paid_order_count", "paid_customer_count"])

    g_r = r_agg.groupby(dim_col).agg(
        refund_amount=("refund_amount", "sum"),
    ) if len(r_agg) else pd.DataFrame(columns=["refund_amount"])

    g = g_o.join(g_r, how="outer").fillna(0.0)
    g["net_sales"] = g["paid_amount"] - g["refund_amount"]
    if metric in (Metric.PAID_AMOUNT, Metric.REFUND_AMOUNT, Metric.NET_SALES):
        g[metric] = g[metric].round(2)
    else:
        g[metric] = g[metric].astype(int)
    return g[[metric]]


def _ratio_divide(num: float, den: float, metric: str):
    """派生比率除法（DM-005）。

    分母为零/缺失时返回 None（绝不能返回 0，0 会被误读成"表现很好"）。
    退款率以百分数呈现（2 位小数）；金额类比率单位为元（2 位小数）。
    """
    if den is None or den <= 0:
        return None
    if metric == Metric.REFUND_RATE:
        return round(num / den * 100, 2)
    return round(num / den, 2)


def _ratio_rows(o: pd.DataFrame, r_agg: pd.DataFrame, metric: str, dim_col):
    """先分别汇总分子、分母，再逐组相除（铁律：严禁对比率求和/平均）。

    返回 (records, zero_denominator_keys)。每条记录附 numerator_value /
    denominator_value，支撑 DM-003 分子分母溯源。
    """
    spec = METRIC_SPEC[metric]
    num_code, den_code = spec["numerator"], spec["denominator"]
    num = _aggregate(o, r_agg, num_code, dim_col)
    den = _aggregate(o, r_agg, den_code, dim_col)

    if dim_col is None:
        nv, dv = float(num or 0.0), float(den or 0.0)
        return ([{metric: _ratio_divide(nv, dv, metric),
                  "numerator_value": round(nv, 2), "denominator_value": round(dv, 2)}],
                [] if dv > 0 else ["（整体）"])

    frame = num.rename(columns={num.columns[0]: "numerator_value"}).join(
        den.rename(columns={den.columns[0]: "denominator_value"}), how="outer").fillna(0.0)
    records, zero_keys = [], []
    for key, row in frame.iterrows():
        nv, dv = float(row["numerator_value"]), float(row["denominator_value"])
        if dv <= 0:
            zero_keys.append(str(key))
        records.append({
            dim_col: str(key),
            metric: _ratio_divide(nv, dv, metric),
            "numerator_value": round(nv, 2),
            "denominator_value": round(dv, 2),
        })
    return records, zero_keys


def _build_sql(plan: dict) -> str:
    metric = plan["metric"]
    filters = plan.get("filters") or {}
    where_o = ["o.pay_status = 'success'",
               f"o.pay_time >= '{plan['date_start']} 00:00:00'",
               f"o.pay_time <= '{plan['date_end']} 23:59:59'"]
    where_r = ["r.refund_status = 'success'",
               f"r.refund_time >= '{plan['date_start']} 00:00:00'",
               f"r.refund_time <= '{plan['date_end']} 23:59:59'"]
    for k, v in filters.items():
        if isinstance(v, (list, tuple)):
            clause = f"c.{k} IN ({', '.join(repr(x) for x in v)})"
        else:
            clause = f"c.{k} = '{v}'"
        where_o.append(clause)
        where_r.append(clause)

    dim = plan.get("group_by") or []
    dim_col = DIMENSION_SPEC[dim[0]]["column"] if dim else None
    sel_group = f"{dim_col}, " if dim_col else ""
    grp = f"\nGROUP BY {dim_col}" if dim_col else ""

    exprs = {
        Metric.PAID_AMOUNT: "SUM(o.pay_amount)",
        Metric.PAID_ORDER_COUNT: "COUNT(DISTINCT o.order_id)",
        Metric.PAID_CUSTOMER_COUNT: "COUNT(DISTINCT o.customer_id)",
    }
    if metric in exprs:
        return (f"SELECT {sel_group}{exprs[metric]} AS {metric}\n"
                f"FROM orders o JOIN customers c ON c.customer_id = o.customer_id\n"
                f"WHERE {' AND '.join(where_o)}{grp};")
    if metric == Metric.REFUND_AMOUNT:
        return (f"SELECT {sel_group}SUM(r.refund_amount) AS refund_amount\n"
                f"FROM refunds r JOIN orders o ON o.order_id = r.order_id\n"
                f"     JOIN customers c ON c.customer_id = o.customer_id\n"
                f"WHERE {' AND '.join(where_r)}{grp};")
    if metric in Metric.RATIO:
        spec = METRIC_SPEC[metric]
        pct = " * 100" if metric == Metric.REFUND_RATE else ""
        dim_join = (f" FULL OUTER JOIN denominator d ON n.{dim_col} = d.{dim_col}"
                    if dim_col else " CROSS JOIN denominator d")

        def component_cte(name: str, code: str) -> str:
            if code == Metric.REFUND_AMOUNT:
                return (f"{name} AS (\n"
                        f"  SELECT {sel_group}SUM(r.refund_amount) AS value\n"
                        f"  FROM refunds r JOIN orders o ON o.order_id = r.order_id\n"
                        f"       JOIN customers c ON c.customer_id = o.customer_id\n"
                        f"  WHERE {' AND '.join(where_r)}{grp}\n)")
            return (f"{name} AS (\n"
                    f"  SELECT {sel_group}{exprs[code]} AS value\n"
                    f"  FROM orders o JOIN customers c ON c.customer_id = o.customer_id\n"
                    f"  WHERE {' AND '.join(where_o)}{grp}\n)")

        return (
            f"-- 派生比率（{spec['label']} = {spec['formula']}）：先汇总分子分母再相除\n"
            f"WITH {component_cte('numerator', spec['numerator'])},\n"
            f"     {component_cte('denominator', spec['denominator'])}\n"
            f"SELECT {('COALESCE(n.' + dim_col + ', d.' + dim_col + ') AS ' + dim_col + ', ') if dim_col else ''}"
            f"n.value AS numerator_value, d.value AS denominator_value,\n"
            f"  CASE WHEN d.value IS NULL OR d.value = 0 THEN NULL\n"
            f"       ELSE ROUND(n.value * 1.0 / d.value{pct}, 2) END AS {metric}\n"
            f"FROM numerator n{dim_join};")
    # 净销售额：两条独立聚合。退款侧先按 order_id 预聚合（refund_pre），
    # 再按维度汇总（refund），最后与支付侧按维度 FULL OUTER JOIN，
    # 与 pandas 执行逻辑（outer join + fillna(0)）逐段对应，
    # 结构上杜绝一对多关联导致实付金额重复累计（契约 IS-001 / §3.4）。
    if dim_col:
        paid_dim = f"c.{dim_col}, "
        pre_group = f"r.order_id, c.{dim_col}"
        final_dim = f"COALESCE(p.{dim_col}, q.{dim_col}) AS {dim_col}, "
        join_clause = f"FULL OUTER JOIN refund q ON p.{dim_col} = q.{dim_col}"
    else:
        paid_dim = ""
        pre_group = "r.order_id"
        final_dim = ""
        # 两个无 GROUP BY 的聚合 CTE 恒为单行，ON 1=1 即一对一
        join_clause = "FULL OUTER JOIN refund q ON 1=1"
    return (
        f"WITH paid AS (\n"
        f"  SELECT {paid_dim}SUM(o.pay_amount) AS paid_amount\n"
        f"  FROM orders o JOIN customers c ON c.customer_id = o.customer_id\n"
        f"  WHERE {' AND '.join(where_o)}{grp}\n"
        f"), refund_pre AS (\n"
        f"  SELECT {'c.' + dim_col + ', ' if dim_col else ''}r.order_id, "
        f"SUM(r.refund_amount) AS refund_amount\n"
        f"  FROM refunds r JOIN orders o ON o.order_id = r.order_id\n"
        f"       JOIN customers c ON c.customer_id = o.customer_id\n"
        f"  WHERE {' AND '.join(where_r)}\n"
        f"  GROUP BY {pre_group}\n"
        f"), refund AS (\n"
        f"  SELECT {sel_group}SUM(refund_amount) AS refund_amount\n"
        f"  FROM refund_pre{grp}\n"
        f")\n"
        f"SELECT {final_dim}"
        f"COALESCE(p.paid_amount, 0) AS paid_amount, "
        f"COALESCE(q.refund_amount, 0) AS refund_amount, "
        f"COALESCE(p.paid_amount, 0) - COALESCE(q.refund_amount, 0) AS net_sales\n"
        f"FROM paid p {join_clause};"
    )


def _run_plan(plan: dict, tables: dict, coverage_months: list | None = None) -> dict:
    metric = plan["metric"]
    dims = plan.get("group_by") or []
    dim_col = DIMENSION_SPEC[dims[0]]["column"] if dims else None
    filters = plan.get("filters") or {}
    cov = _coverage(coverage_months)

    o, r_agg = _slice_period(tables, plan["date_start"], plan["date_end"])
    o = _apply_filters(o, filters)
    r_agg = _apply_filters(r_agg, filters)

    warnings = []
    if not len(o):
        warnings.append({
            "level": "warning",
            "code": "empty_result",
            "message": f"{plan['date_start']} 至 {plan['date_end']} 期间没有符合条件的成功支付订单。",
            "impact": "结果为空，不代表该期间销售额为零，请确认筛选条件是否正确。",
        })

    is_ratio = metric in Metric.RATIO
    zero_keys: list = []

    if is_ratio:
        # 派生比率：分子、分母各自独立聚合后再相除（DM-001/铁律）
        records, zero_keys = _ratio_rows(o, r_agg, metric, dim_col)
        result = pd.DataFrame(records)
        if dim_col:
            result = result.sort_values(
                metric, ascending=(plan.get("sort") == "asc"), na_position="last")
    else:
        result = _aggregate(o, r_agg, metric, dim_col)

    if plan.get("comparison") == "mom":
        months = _months_between(plan["date_start"], plan["date_end"])
        p_start = _month_start(_shift_month(months[0], -1))
        p_end = _month_end(_shift_month(months[-1], -1))
        po, pr = _slice_period(tables, p_start, p_end)
        po = _apply_filters(po, filters)
        pr = _apply_filters(pr, filters)
        if is_ratio:
            prev_records, _ = _ratio_rows(po, pr, metric, dim_col)
            if dim_col:
                prev_map = {row[dim_col]: row[metric] for row in prev_records}
                result["prev_value"] = result[dim_col].map(prev_map)
            elif prev_records:
                result["prev_value"] = prev_records[0][metric]
        else:
            prev = _aggregate(po, pr, metric, dim_col)
            if len(prev):
                prev.columns = ["prev_value"]
                result = result.join(prev, how="left")
        if p_start < cov["start"]:
            warnings.append({
                "level": "info",
                "code": "previous_period_partial",
                "message": f"对比期 {p_start} 至 {p_end} 超出数据覆盖范围。",
                "impact": "环比结果可能不完整。",
            })

    if not is_ratio:
        if dim_col:
            result = result.reset_index().rename(columns={dim_col: dim_col})
            result = result.sort_values(metric, ascending=(plan.get("sort") == "asc"))
        else:
            result = pd.DataFrame([{metric: result}])

    if is_ratio and zero_keys:
        where = f"（{', '.join(zero_keys)}）" if dim_col else ""
        den_label = METRIC_SPEC[METRIC_SPEC[metric]["denominator"]]["label"]
        warnings.append({
            "level": "warning",
            "code": "NON_POSITIVE_DENOMINATOR",
            "message": f"{METRIC_SPEC[metric]['label']}的分母（{den_label}）为 0{where}，对应结果返回 null。",
            "impact": "null 表示分母为零、无法计算，不是比率为 0%；请勿按 0 解读或参与平均。",
        })

    limit = int(plan.get("limit") or 100)
    truncated = len(result) > limit
    result = result.head(limit)

    coverage_warn = []
    if plan["date_start"] < cov["start"] or plan["date_end"] > cov["end"]:
        coverage_warn.append({
            "level": "warning",
            "code": "out_of_coverage",
            "message": f"查询区间超出数据覆盖范围 {cov['start']} ~ {cov['end']}。",
            "impact": "区间外的部分按 0 计入，指标可能被低估。",
        })
    warnings.extend(coverage_warn)

    return {
        "data": result.to_dict(orient="records"),
        "columns": list(result.columns),
        "row_count": int(len(result)),
        "truncated": truncated,
        "warnings": warnings,
        "generated_sql": _build_sql(plan),
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def _handle_inner(question: str, context: dict | None = None,
                  clarification: dict | None = None,
                  tables: dict | None = None,
                  coverage_months: list | None = None) -> dict:
    """生成结果信封（内部实现，不涉及数据集版本）。"""
    cov = _coverage(coverage_months)
    if tables is None:
        from demo_data import demo_tables
        tables = demo_tables()

    ctx = dict(context or {})
    ctx.pop("__empty__", None)
    rounds = int(ctx.get("clarification_round", 0))

    if clarification:
        target = clarification.get("target_field") or clarification_field(clarification.get("id", ""))
        raw = clarification.get("free_text") or clarification.get("choice")
        if target and raw:
            value = _normalize_choice(target, raw)
            if target in ("metric", "criterion"):
                ctx["metric"] = value
            elif target == "date_range":
                ctx["date_start"] = _month_start(value)
                ctx["date_end"] = _month_end(value)
            elif target == "group_by":
                ctx["group_by"] = [value]
        rounds += 1
    ctx["clarification_round"] = rounds

    q = (question or "").strip()
    if not q:
        return _envelope(Status.INSUFFICIENT_DATA, "问题为空。",
                         reason="empty_question", missing=["问题内容"],
                         suggestion="请输入一个具体的经营数据问题。", retryable=False,
                         context=ctx)

    rejected = _reject(q)
    if rejected:
        status, msg, reason, missing, suggestion, retryable = rejected
        return _envelope(status, msg, reason=reason, missing=missing,
                         suggestion=suggestion, retryable=retryable, context=ctx)

    # ---- 指标 ----
    m_state, m_val = _detect_metric(q, ctx)

    # 用户要求按字典未定义的口径计算：必须说明冲突，不得默默返回标准口径的数字
    if m_state == "ok":
        hit = next((p for p in CONFLICT_PHRASES if p in q), None)
        if hit:
            spec_c = METRIC_SPEC[m_val]
            return _envelope(
                Status.OUT_OF_SCOPE,
                f"你描述的口径与指标字典冲突：「{hit}」。",
                reason="metric_definition_conflict",
                missing=[f"符合「{hit}」要求的 {spec_c['label']} 派生口径定义"],
                suggestion=f"字典中「{spec_c['label']}」的定义是：{spec_c['definition']}。"
                           f"如果你确实需要按上述口径计算，请先在业务字典中新增指标；"
                           f"否则请去掉「{hit}」后重新提问。",
                retryable=False, context=ctx)

    if m_state == "ambiguous":
        if rounds >= MAX_CLARIFICATION_ROUNDS:
            return _envelope(Status.INSUFFICIENT_DATA, "连续澄清后仍未确定指标口径。",
                             reason="clarification_exhausted", missing=["明确的指标口径"],
                             suggestion="请直接指定 5 个基础指标之一，例如「净销售额」。",
                             retryable=False, context=ctx)
        return _envelope(
            Status.NEED_CLARIFICATION, "指标口径不明确，需要你确认。",
            reason=ReasonCode.AMBIGUOUS_METRIC,
            clarification=_build_clarification(
                "metric", ReasonCode.AMBIGUOUS_METRIC,
                f"你说的「{_matched_ambiguous_term(q)}」是指哪一个指标？",
                _metric_options(m_val), ctx),
            context=ctx)
    if m_state == "missing":
        if any(w in q for w in CRITERION_WORDS):
            if rounds >= MAX_CLARIFICATION_ROUNDS:
                return _envelope(Status.INSUFFICIENT_DATA, "连续澄清后仍未确定评价标准。",
                                 reason="clarification_exhausted", missing=["评价指标"],
                                 suggestion="请指明用哪个指标评价，例如「净销售额最高的地区」。",
                                 retryable=False, context=ctx)
            return _envelope(
                Status.NEED_CLARIFICATION, "评价标准不明确，需要你确认。",
                reason=ReasonCode.AMBIGUOUS_CRITERION,
                clarification=_build_clarification(
                    "metric", ReasonCode.AMBIGUOUS_CRITERION,
                    "用哪一个指标来评价「最好」？",
                    _metric_options([Metric.NET_SALES, Metric.PAID_AMOUNT,
                                     Metric.PAID_ORDER_COUNT, Metric.PAID_CUSTOMER_COUNT]), ctx),
                context=ctx)
        if rounds >= MAX_CLARIFICATION_ROUNDS:
            return _envelope(Status.INSUFFICIENT_DATA, "连续澄清后仍未确定指标。",
                             reason="clarification_exhausted", missing=["指标"],
                             suggestion="请直接说明要看哪个指标。", retryable=False, context=ctx)
        return _envelope(
            Status.NEED_CLARIFICATION, "没有识别出要查询的指标。",
            reason=ReasonCode.MISSING_FIELD,
            clarification=_build_clarification(
                "metric", ReasonCode.MISSING_FIELD, "你想查询哪一个指标？",
                _metric_options(list(Metric.ALL)), ctx),
            context=ctx)

    # ---- 时间 ----
    p_state, ds, de = _detect_period(q, ctx, coverage_months)
    if p_state in ("ambiguous", "missing"):
        if rounds >= MAX_CLARIFICATION_ROUNDS:
            return _envelope(Status.INSUFFICIENT_DATA, "连续澄清后仍未确定时间范围。",
                             reason="clarification_exhausted", missing=["时间范围"],
                             suggestion="请给出明确的时间范围，例如「2026年9月」。",
                             retryable=False, context=ctx)
        ask = "「最近」具体指哪一段时间？" if p_state == "ambiguous" else "你想查询哪一段时间？"
        return _envelope(
            Status.NEED_CLARIFICATION, "时间范围不明确，需要你确认。",
            reason=ReasonCode.AMBIGUOUS_TIME_RANGE if p_state == "ambiguous" else ReasonCode.MISSING_FIELD,
            clarification=_build_clarification(
                "date_range",
                ReasonCode.AMBIGUOUS_TIME_RANGE if p_state == "ambiguous" else ReasonCode.MISSING_FIELD,
                ask,
                [{"value": m, "label": m.replace("-", " 年 ") + " 月",
                  "definition": f"数据覆盖 {_month_start(m)} ~ {_month_end(m)}"}
                 for m in cov["months"]], ctx),
            context=ctx)

    if p_state == "out_of_coverage":
        return _envelope(
            Status.INSUFFICIENT_DATA,
            f"数据未覆盖 {ds} 至 {de}。",
            reason="period_out_of_coverage",
            missing=[f"{ds} ~ {de} 的业务数据"],
            suggestion=f"当前数据覆盖范围为 {cov['start']} ~ {cov['end']}，"
                       f"请改为该区间内的时间。",
            retryable=False, context=ctx)

    # ---- 组装查询计划 ----
    ctx.update({"metric": m_val, "date_start": ds, "date_end": de})
    group_by = _detect_group_by(q, ctx)
    ctx["group_by"] = group_by
    filters = _detect_filters(q, ctx)
    ctx["filters"] = filters

    plan = {
        "metric": m_val,
        "date_start": ds,
        "date_end": de,
        "group_by": group_by,
        "filters": filters,
        "sort": _detect_sort(q),
        "limit": 100,
        "comparison": _detect_comparison(q),
    }

    try:
        out = _run_plan(plan, tables, coverage_months)
    except Exception as exc:  # noqa: BLE001
        return _envelope(Status.EXECUTION_FAILED, "查询执行失败。",
                         reason="execution_error", missing=[],
                         suggestion=f"请将以下错误信息反馈给成员 1：{exc}",
                         retryable=True, context=ctx, plan=plan,
                         warnings=[], generated_sql="")

    spec = METRIC_SPEC[m_val]
    extra = {}
    if spec.get("kind") == "ratio":
        # DM-003：派生比率返回分子分母溯源（逐行分量在 data[*].numerator_value）
        extra["metric_kind"] = "ratio"
        extra["components"] = {
            "numerator_metric": spec["numerator"],
            "denominator_metric": spec["denominator"],
            "rule": "先汇总分子分母，再相除；分母为零时返回 null",
        }
    return _envelope(
        Status.SUCCESS,
        f"已按「{spec['label']}」口径完成查询。",
        data=out["data"],
        columns=out["columns"],
        definition=spec["definition"],
        unit=spec["unit"],
        metric=m_val,
        applied_filters=plan["filters"],
        date_start=plan["date_start"],
        date_end=plan["date_end"],
        group_by=plan["group_by"],
        source_tables=spec["source_tables"],
        generated_sql=out["generated_sql"],
        warnings=out["warnings"],
        row_count=out["row_count"],
        truncated=out["truncated"],
        plan=plan,
        context=ctx,
        **extra,
    )


def handle(question: str, context: dict | None = None,
           clarification: dict | None = None, tables: dict | None = None,
           dataset_version: str | None = None,
           coverage_months: list | None = None) -> dict:
    """完整处理一次提问，返回契约定义的结果信封。

    :param question: 用户原话（澄清二次提交时，仍传原始问题）
    :param context: 上一轮返回的 resolved_context，原样回传
    :param clarification: {"id","choice","free_text"} —— 仅澄清后提交时提供
    :param tables: 数据源；为空时使用内置演示数据
    :param dataset_version: 数据集版本号。由调用方从 dataset_registry 取，
                            使每次查询的来源可追溯，而不是一个写死的常量。
                            这是 §5.4「每次成功查询都能查看口径和来源」的前提。
    :param coverage_months: 数据覆盖月份（YYYY-MM），取自数据集显式元数据；
                            为空时用契约内置演示数据的覆盖区间。
    """
    resp = _handle_inner(question, context=context, clarification=clarification,
                         tables=tables, coverage_months=coverage_months)
    if dataset_version:
        resp["dataset_version"] = dataset_version
    return resp


def _matched_ambiguous_term(question: str) -> str:
    for term in sorted(AMBIGUOUS_METRIC_TERMS, key=len, reverse=True):
        if term in question:
            return term
    return "该词"
