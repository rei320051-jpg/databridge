# -*- coding: utf-8 -*-
"""数据质量检查（页面侧实现）。

职责边界说明（重要）：
  正式的数据导入与质量检查是**成员 1 的主责**（分工文档 §3.2.4、§7）。
  本模块是**成员 3 的测试用对照实现**，用途有两个：
    1. 接口未就绪时让「数据接入区」有真实内容可展示；
    2. 当成员 1 的 /datasets/inspect 上线后，用同一批异常数据对比两边结论是否一致。
  正式结论必须以成员 1 的接口返回为准。

检查项对齐分工文档 §3.2.4 的 8 条。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.contracts import WarningLevel  # noqa: E402

try:
    from demo_data import TABLE_SCHEMA
except ImportError:  # pragma: no cover
    TABLE_SCHEMA = {}

AMOUNT_HINTS = ("amount", "金额", "price", "价格", "费用", "fee", "cost")
TIME_HINTS = ("time", "date", "时间", "日期")
ID_HINTS = ("_id", "编号", "id")


def _is_amount(col: str) -> bool:
    c = str(col).lower()
    return any(h in c for h in AMOUNT_HINTS)


def _is_time(col: str) -> bool:
    c = str(col).lower()
    return any(h in c for h in TIME_HINTS)


def _is_id(col: str) -> bool:
    c = str(col).lower()
    return c.endswith("_id") or c == "id" or "编号" in c or c.endswith("no")


def _infer_type(series: pd.Series) -> str:
    if pd.api.types.is_numeric_dtype(series):
        return "数值"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "时间"
    sample = series.dropna().astype(str).head(500)
    if len(sample) and pd.to_datetime(sample, errors="coerce").notna().mean() > 0.9:
        return "时间"
    if len(sample) and pd.to_numeric(sample, errors="coerce").notna().mean() > 0.9:
        return "数值"
    return "文本"


def infer_table_name(filename: str) -> str:
    """按文件名识别表。必须包含 order / refund / customer 之一。"""
    low = str(filename).lower()
    if "refund" in low or "退款" in low:
        return "refunds"
    if "order" in low or "订单" in low:
        return "orders"
    if "customer" in low or "客户" in low:
        return "customers"
    return Path(str(filename)).stem


def inspect_table(name: str, df: pd.DataFrame) -> dict:
    schema = TABLE_SCHEMA.get(name, {})
    issues: list = []

    def add(level, code, field, count, message, impact):
        issues.append({
            "level": level, "code": code, "field": field,
            "count": int(count), "message": message, "impact": impact,
        })

    # 1) 必需字段是否存在
    required = schema.get("required", [])
    for col in required:
        if col not in df.columns:
            add(WarningLevel.ERROR, "missing_column", col, 0,
                f"缺少必需字段 `{col}`。",
                "该表无法参与指标计算，相关查询会直接失败。")

    # 2) 列名重复 / 空表
    dup_cols = [c for c in df.columns[df.columns.duplicated()]]
    for c in set(dup_cols):
        add(WarningLevel.ERROR, "duplicate_column", c, int(list(df.columns).count(c)) - 1,
            f"列名 `{c}` 重复出现。",
            "读取时后一列会覆盖前一列，字段含义不确定。")

    # 3) 主键重复
    pk = schema.get("primary_key")
    if pk and pk in df.columns:
        dup_n = int(df[pk].duplicated().sum())
        if dup_n:
            add(WarningLevel.ERROR, "duplicate_primary_key", pk, dup_n,
                f"主键 `{pk}` 存在 {dup_n} 条重复记录。",
                "按主键去重的指标（订单数、支付人数）会被低估，金额类指标会被高估。")

    if not schema and len(df.columns):
        candidate = next((c for c in df.columns if _is_id(c)), None)
        if candidate is not None:
            dup_n = int(df[candidate].duplicated().sum())
            if dup_n:
                add(WarningLevel.WARNING, "duplicate_id_candidate", candidate, dup_n,
                    f"疑似主键 `{candidate}` 有 {dup_n} 条重复。",
                    "若该列确为主键，则相关指标不可信。")

    # 4) 必需值缺失
    for col in df.columns:
        n_null = int(df[col].isna().sum())
        if not n_null:
            continue
        ratio = n_null / max(1, len(df))
        required_col = (not required) or (col in required)
        level = WarningLevel.ERROR if (required_col and ratio > 0.5) else WarningLevel.WARNING
        add(level, "missing_value", col, n_null,
            f"字段 `{col}` 有 {n_null} 条空值（占 {ratio:.1%}）。",
            "缺失值默认被忽略，会导致分组统计口径不一致。")

    # 5) 金额负数 / 异常值
    for col in df.columns:
        if not _is_amount(col):
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        neg_n = int((s < 0).sum())
        if neg_n:
            add(WarningLevel.ERROR, "negative_amount", col, neg_n,
                f"金额字段 `{col}` 存在 {neg_n} 条负值。",
                "负金额会被直接求和进入指标，拉低金额类指标。")
        valid = s.dropna()
        if len(valid) >= 20:
            q1, q3 = valid.quantile(0.25), valid.quantile(0.75)
            iqr = q3 - q1
            if iqr > 0:
                # 阈值取 Q3 + 6*IQR：既要抓出录入错误造成的数量级异常，
                # 又不能把正常长尾交易的抖动误报为问题（干净数据应当 0 警告）
                upper = q3 + 6 * iqr
                out_n = int((valid > upper).sum())
                if out_n:
                    ratio = float(valid.max()) / float(valid.median() or 1)
                    add(WarningLevel.WARNING, "amount_outlier", col, out_n,
                        f"金额字段 `{col}` 有 {out_n} 条极端大值（> {upper:,.0f}），"
                        f"最大值为中位数的 {ratio:,.0f} 倍。",
                        "若为测试数据或录入错误，金额类指标会被显著抬高。")

    # 6) 时间字段是否可解析
    for col in df.columns:
        if not _is_time(col):
            continue
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            continue
        bad = pd.to_datetime(df[col], errors="coerce").isna() & df[col].notna()
        bad_n = int(bad.sum())
        if bad_n:
            samples = df.loc[bad, col].astype(str).head(3).tolist()
            add(WarningLevel.ERROR, "unparsable_time", col, bad_n,
                f"时间字段 `{col}` 有 {bad_n} 条无法解析，例如 {samples}。",
                "该批记录会被排除在时间筛选之外，期间指标偏低。")

    # 7) 时间覆盖范围
    for col in df.columns:
        if not _is_time(col):
            continue
        ts = pd.to_datetime(df[col], errors="coerce").dropna()
        if len(ts):
            span_days = (ts.max() - ts.min()).days
            if span_days < 7:
                add(WarningLevel.INFO, "narrow_time_span", col, len(ts),
                    f"时间字段 `{col}` 仅覆盖 {span_days} 天。",
                    "不足以支持月度或季度对比类问题。")

    # 8) 重复整行
    full_dup = int(df.duplicated().sum())
    if full_dup:
        add(WarningLevel.WARNING, "duplicate_row", "*", full_dup,
            f"存在 {full_dup} 条完全重复的记录。",
            "若为脏数据会导致金额重复累计。")

    field_types = {str(c): _infer_type(df[c]) for c in dict.fromkeys(df.columns)}
    return {
        "name": name,
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "primary_key": pk or "(未声明)",
        "field_types": field_types,
        "issues": issues,
        "error_count": sum(1 for i in issues if i["level"] == WarningLevel.ERROR),
        "warning_count": sum(1 for i in issues if i["level"] == WarningLevel.WARNING),
    }


def _check_foreign_keys(tables: dict) -> list:
    issues = []
    for name, schema in TABLE_SCHEMA.items():
        if name not in tables:
            continue
        df = tables[name]
        for fk_col, target in (schema.get("foreign_keys") or {}).items():
            t_table, t_col = target.split(".")
            if fk_col not in df.columns or t_table not in tables:
                continue
            tdf = tables[t_table]
            if t_col not in tdf.columns:
                continue
            valid = set(tdf[t_col].dropna().astype(str))
            keys = df[fk_col].dropna().astype(str)
            orphan = int((~keys.isin(valid)).sum())
            if orphan:
                issues.append({
                    "level": WarningLevel.ERROR,
                    "code": "orphan_foreign_key",
                    "field": f"{name}.{fk_col} -> {target}",
                    "count": orphan,
                    "message": f"`{name}.{fk_col}` 有 {orphan} 条无法在 `{target}` 中找到对应记录。",
                    "impact": "关联后这些记录的分组维度会变成空值，按地区统计时总额对不上。",
                })
    return issues


def inspect_datasets(tables: dict, version: str = "") -> dict:
    """对一组表做完整质量检查，返回可直接展示的报告字典。"""
    table_reports = [inspect_table(n, df) for n, df in tables.items()]
    cross = _check_foreign_keys(tables)

    issues: list = []
    for r in table_reports:
        for i in r["issues"]:
            issues.append({**i, "table": r["name"]})
    issues.extend({**i, "table": "跨表"} for i in cross)

    return {
        "status": "ok",
        "dataset_version": version,
        "tables": table_reports,
        "cross_table_issues": cross,
        "issues": issues,
        "total_errors": sum(1 for i in issues if i["level"] == WarningLevel.ERROR),
        "total_warnings": sum(1 for i in issues if i["level"] == WarningLevel.WARNING),
        "inspected_at": pd.Timestamp.now().isoformat(timespec="seconds"),
    }
