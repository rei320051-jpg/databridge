# -*- coding: utf-8 -*-
"""正式联调库适配层：把成员 1 的物理数据集（data/demo，demo-v1.0）转成
页面/mock_backend 消费的内存表形态。

为什么需要它
------------
页面 mock 管线（demo_data / mock_backend）与成员 1 的 SQLite 执行层
（databridge/，schema.sql）使用**不同的物理约定**，但对外指标口径一致。
本模块只做机械的物理形态转换，让同一份正式库既能被正式后端查询，
也能在 mock 模式下被页面加载 —— 这是「页面与外部 Agent 同源同数」
（F07、分工文档 §3.4）的前提。

转换规则（对应 docs/data_dictionary.md v0.1）
-------------------------------------------
| 页面/契约形态            | 正式库物理形态                 | 处理 |
|-------------------------|------------------------------|------|
| orders.pay_time         | orders.paid_at               | 改名；未支付为空时回填 ordered_at（不参与统计）|
| orders.order_time       | orders.ordered_at            | 改名 |
| orders.pay_status       | orders.payment_status        | paid→success；cancelled/failed 原样 |
| orders.pay_amount（元） | paid_amount_fen（整数分）    | /100 |
| refunds.refund_time     | refunds.refunded_at          | 改名；非成功行空值回填 requested_at |
| refunds.refund_amount   | refund_amount_fen            | /100 |
| customers.region        | orders.region（订单快照）    | 按客户聚合（见下）|
| customers.customer_type | new / returning              | 新客户 / 老客户 |
| customers.register_date | created_at                   | 改名 |

唯一无法机械映射的差异是**地区词表**：正式库为 4 地区（华东/华南/华北/西部），
shared/contracts.py 冻结的是 5 地区（华东/华南/华北/西南/华中）。
本适配不擅自改值，保留数据原值并在 FORMAL_DATASET_NOTES 中显式标注
region_vocab_conflict，最终词表由三人按 DS-001 决策后统一。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

FORMAL_DEMO_DIR = _ROOT / "data" / "demo"
FORMAL_VERSION = "demo-v1.0"
#: 覆盖月份，来自 data/demo/metadata.json 的显式元数据
#: （coverage_start=2026-01-01, coverage_end_exclusive=2026-10-01）。
#: 不按最早/最晚交易推断。
FORMAL_COVERAGE_MONTHS = [f"2026-{m:02d}" for m in range(1, 10)]

#: 客户类型：物理码 -> 对外中文标签（与金额的分->元一样，属于边界映射）
CUSTOMER_TYPE_MAP = {"new": "新客户", "returning": "老客户"}
#: 订单支付状态：物理码 -> 契约状态码
PAY_STATUS_MAP = {"paid": "success", "cancelled": "cancelled", "failed": "failed"}

#: 适配层已知差异（页面据此显示提示，不隐瞒不一致）
FORMAL_DATASET_NOTES = {
    "version": FORMAL_VERSION,
    "source": "成员 1 正式演示库 data/demo（通过导入器校验，sha256 锁定）",
    "coverage": "2026-01-01 ~ 2026-09-30",
    "unit": "接口金额为整数分，本适配在边界换算为元（/100）",
    "region_vocab_conflict": (
        "正式库地区为 华东/华南/华北/西部（4 个），契约词表为 "
        "华东/华南/华北/西南/华中（5 个）。在 DS-001 决策前保留数据原值，"
        "两套数据集的数字不得混用或相互比较。"
    ),
}


def _read_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(FORMAL_DEMO_DIR / name, dtype=str, keep_default_na=False,
                       na_values=[""]).reset_index(drop=True)


def load_formal_demo() -> dict:
    """读取正式 demo-v1.0 CSV 并转换为页面消费形态 {customers, orders, refunds}。"""
    orders_raw = pd.read_csv(FORMAL_DEMO_DIR / "orders.csv")
    refunds_raw = pd.read_csv(FORMAL_DEMO_DIR / "refunds.csv")
    customers_raw = pd.read_csv(FORMAL_DEMO_DIR / "customers.csv")

    ctype_by_customer = customers_raw.set_index("customer_id")["customer_type"].map(
        CUSTOMER_TYPE_MAP)

    # --- orders（地区与客户类型为订单快照，直接随行保留，不提升到客户维度）---
    orders = pd.DataFrame({
        "order_id": orders_raw["order_id"].astype(str),
        "customer_id": orders_raw["customer_id"].astype(str),
        "order_time": orders_raw["ordered_at"].str.replace("T", " ", regex=False),
        # 未成功支付 paid_at 为空：回填下单时间，保证可解析；pay_status 非 success 不会参与统计
        "pay_time": (orders_raw["paid_at"].fillna(orders_raw["ordered_at"])
                     .str.replace("T", " ", regex=False)),
        "pay_status": orders_raw["payment_status"].map(PAY_STATUS_MAP).fillna(
            orders_raw["payment_status"]),
        "pay_amount": (pd.to_numeric(orders_raw["paid_amount_fen"], errors="coerce")
                       .fillna(0) / 100.0).round(2),
        "region": orders_raw["region"].astype(str),
        "customer_type": orders_raw["customer_id"].map(ctype_by_customer).fillna(""),
    })

    # --- refunds ---
    refunds = pd.DataFrame({
        "refund_id": refunds_raw["refund_id"].astype(str),
        "order_id": refunds_raw["order_id"].astype(str),
        "refund_time": (refunds_raw["refunded_at"].fillna(refunds_raw["requested_at"])
                        .str.replace("T", " ", regex=False)),
        "refund_status": refunds_raw["refund_status"],
        "refund_amount": (pd.to_numeric(refunds_raw["refund_amount_fen"], errors="coerce")
                          .fillna(0) / 100.0).round(2),
    })

    # --- customers ---
    # 地区在正式库中是订单快照（orders.region）。演示数据内同一客户的地区唯一，
    # 用众数归到客户维度供页面 join；若出现跨地区客户，取最近订单地区（防御，正常为 0 例）。
    region_map = (orders_raw.assign(_t=pd.to_datetime(orders_raw["ordered_at"], errors="coerce"))
                  .sort_values("_t")
                  .groupby("customer_id")["region"].last())
    customers = pd.DataFrame({
        "customer_id": customers_raw["customer_id"].astype(str),
        "customer_name": "客户" + customers_raw["customer_id"].astype(str),
        "region": customers_raw["customer_id"].map(region_map).fillna("未知"),
        "customer_type": customers_raw["customer_type"].map(CUSTOMER_TYPE_MAP).fillna(
            customers_raw["customer_type"]),
        "register_date": (pd.to_datetime(customers_raw["created_at"], errors="coerce")
                          .dt.strftime("%Y-%m-%d")),
    })

    return {"customers": customers, "orders": orders, "refunds": refunds}


def formal_expected() -> dict:
    """读取成员 1 的标准答案 expected.json（供交叉验证，不参与查询）。"""
    return json.loads((FORMAL_DEMO_DIR / "expected.json").read_text(encoding="utf-8"))


def cross_region_customers() -> int:
    """统计同一客户出现在多个地区的订单数（应为 0；非 0 则快照归属存在歧义）。"""
    orders_raw = pd.read_csv(FORMAL_DEMO_DIR / "orders.csv")
    return int((orders_raw.groupby("customer_id")["region"].nunique() > 1).sum())
