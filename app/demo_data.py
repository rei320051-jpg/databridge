# -*- coding: utf-8 -*-
"""演示数据生成（成员 3 页面自测用，正式数据集由成员 1 交付）。

设计要点：
1. 先生成 orders / refunds / customers 三张真实结构的表，再由表计算指标 ——
   保证页面展示的数字是真实计算结果，而不是硬编码常量。
2. 月度、地区的「实付金额」总量由 BASE_PAID 精确控制，
   「成功退款金额」总量由 REFUND_RATE 精确控制，因此环比故事稳定可复现。
3. 订单表内故意混入 pay_status = failed / pending 的干扰行，
   用于验证「取消订单、失败支付和失败退款不参与统计」这一口径。
4. 客户数、订单数由实际生成的行推导，不预设目标值。

注意：本文件是页面占位数据。正式演示数据与标准答案由成员 1 提供。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SEED = 20260930

REGIONS = ["华东", "华南", "华北", "西南", "华中"]
REGION_CODE = {"华东": "HD", "华南": "HN", "华北": "HB", "西南": "XN", "华中": "HZ"}
MONTHS = ["2026-06", "2026-07", "2026-08", "2026-09"]

#: 各地区的「成功支付实付金额」月度总量（单位：元）
BASE_PAID = {
    "华东": {"2026-06": 1352000.0, "2026-07": 1420000.0, "2026-08": 1490000.0, "2026-09": 1268000.0},
    "华南": {"2026-06": 1021000.0, "2026-07": 1085000.0, "2026-08": 1112000.0, "2026-09": 1146000.0},
    "华北": {"2026-06": 788000.0, "2026-07": 815000.0, "2026-08": 842000.0, "2026-09": 765000.0},
    "西南": {"2026-06": 512000.0, "2026-07": 548000.0, "2026-08": 587000.0, "2026-09": 617000.0},
    "华中": {"2026-06": 735000.0, "2026-07": 721000.0, "2026-08": 704000.0, "2026-09": 675000.0},
}

#: 成功退款金额占实付金额的比例（按地区、月）
REFUND_RATE = {
    "华东": {"2026-06": 0.092, "2026-07": 0.094, "2026-08": 0.101, "2026-09": 0.088},
    "华南": {"2026-06": 0.071, "2026-07": 0.070, "2026-08": 0.068, "2026-09": 0.072},
    "华北": {"2026-06": 0.085, "2026-07": 0.083, "2026-08": 0.079, "2026-09": 0.091},
    "西南": {"2026-06": 0.062, "2026-07": 0.060, "2026-08": 0.058, "2026-09": 0.061},
    "华中": {"2026-06": 0.078, "2026-07": 0.080, "2026-08": 0.076, "2026-09": 0.074},
}

#: 地区客单价，仅用于推算订单条数量级
AOV = {"华东": 268.0, "华南": 231.0, "华北": 205.0, "西南": 186.0, "华中": 197.0}

#: 每个地区的客户复购倍数，用于推算客户池规模
REPEAT = {"华东": 1.45, "华南": 1.40, "华北": 1.35, "西南": 1.25, "华中": 1.38}


def _order_counts() -> dict:
    return {
        r: {m: max(1, int(round(BASE_PAID[r][m] / AOV[r]))) for m in MONTHS}
        for r in REGIONS
    }


def _seq_ids(prefix: str, start: int, n: int, width: int) -> np.ndarray:
    """向量化生成编号数组，例如 O0000001 … O0000007。"""
    nums = np.char.zfill(np.arange(start, start + n).astype(str), width)
    return np.char.add(prefix, nums)


def _make_customers(rng: np.random.Generator) -> pd.DataFrame:
    counts = _order_counts()
    frames = []
    for region in REGIONS:
        pool = max(10, int(round(sum(counts[region].values()) / REPEAT[region])))
        idx = np.arange(1, pool + 1)
        zf = np.char.zfill(idx.astype(str), 5)
        frames.append(pd.DataFrame({
            "customer_id": np.char.add(f"C{REGION_CODE[region]}", zf),
            "customer_name": np.char.add(f"{region}客户", zf),
            "region": region,
            "customer_type": rng.choice(np.array(["新客户", "老客户"]), size=pool, p=[0.35, 0.65]),
            "register_date": (pd.Timestamp("2025-06-01")
                              + pd.to_timedelta(rng.integers(0, 480, pool), unit="D")
                              ).strftime("%Y-%m-%d"),
        }))
    return pd.concat(frames, ignore_index=True)


def _split_amount(total: float, n: int, rng: np.random.Generator) -> np.ndarray:
    """把总量 total 随机拆成 n 笔正数，且和精确等于 total。"""
    w = rng.gamma(5.0, 1.0, n)
    w = w / w.sum()
    amts = np.round(total * w, 2)
    amts[int(np.argmax(amts))] += round(total - float(amts.sum()), 2)
    return amts


def _make_orders_refunds(rng: np.random.Generator, customers: pd.DataFrame):
    """向量化生成订单与退款表。

    关键约束（改动时必须保持）：
      - 同一地区同一月的成功订单，其实付金额之和精确等于 BASE_PAID；
      - 退款只挂在**同地区同月**的成功订单上，否则经 orders -> customers 关联后
        退款会错误地落到别的地区；
      - 退款时间限制在本月内，保证「同期」归属与设计的月度口径一致。
    """
    counts = _order_counts()
    pools = {r: customers.loc[customers["region"] == r, "customer_id"].to_numpy() for r in REGIONS}
    order_frames, refund_frames = [], []
    o_seq, r_seq = 1, 1

    for region in REGIONS:
        pool = pools[region]
        for month in MONTHS:
            n = counts[region][month]
            total = BASE_PAID[region][month]
            start = pd.Timestamp(month + "-01")
            end = start + pd.offsets.MonthEnd(0)
            span = float((end - start).total_seconds())
            month_end = pd.Timestamp(end.date()) + pd.Timedelta(hours=23, minutes=59, seconds=59)

            def _timestamps(k):
                t = start + pd.to_timedelta(rng.uniform(0, span, k), unit="s")
                return t

            # --- 正常成功订单 ---
            ts = _timestamps(n)
            success_ids = _seq_ids("O", o_seq, n, 7)
            order_frames.append(pd.DataFrame({
                "order_id": success_ids,
                "customer_id": rng.choice(pool, size=n),
                "order_time": (ts - pd.to_timedelta(rng.integers(1, 240, n), unit="m")).strftime("%Y-%m-%d %H:%M:%S"),
                "pay_time": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "pay_status": "success",
                "pay_amount": _split_amount(total, n, rng),
            }))
            o_seq += n

            # --- 干扰订单：失败支付 / 待支付 / 已取消，不得参与统计 ---
            n_noise = max(1, int(round(n * 0.04)))
            ts_n = _timestamps(n_noise)
            order_frames.append(pd.DataFrame({
                "order_id": _seq_ids("O", o_seq, n_noise, 7),
                "customer_id": rng.choice(pool, size=n_noise),
                "order_time": (ts_n - pd.to_timedelta(rng.integers(1, 240, n_noise), unit="m")).strftime("%Y-%m-%d %H:%M:%S"),
                "pay_time": ts_n.strftime("%Y-%m-%d %H:%M:%S"),
                "pay_status": rng.choice(np.array(["failed", "pending", "cancelled"]),
                                         size=n_noise, p=[0.5, 0.3, 0.2]),
                "pay_amount": _split_amount(total * 0.05, n_noise, rng),
            }))
            o_seq += n_noise

            # --- 成功退款：金额总量精确等于 total * rate ---
            refund_total = round(total * REFUND_RATE[region][month], 2)
            n_ref = max(1, int(round(n * 0.07)))
            rts = pd.DatetimeIndex(
                np.minimum(
                    (_timestamps(n_ref) + pd.to_timedelta(rng.integers(0, 16, n_ref), unit="D")
                     ).values.astype("int64"),
                    np.int64(month_end.value),
                )
            )
            refund_frames.append(pd.DataFrame({
                "refund_id": _seq_ids("R", r_seq, n_ref, 6),
                "order_id": rng.choice(success_ids, size=n_ref),
                "refund_time": rts.strftime("%Y-%m-%d %H:%M:%S"),
                "refund_status": "success",
                "refund_amount": _split_amount(refund_total, n_ref, rng),
            }))
            r_seq += n_ref

            # --- 干扰退款：失败退款，不得参与统计 ---
            n_fail = max(1, int(round(n * 0.012)))
            rts_f = pd.DatetimeIndex(
                np.minimum(
                    (_timestamps(n_fail) + pd.to_timedelta(rng.integers(0, 16, n_fail), unit="D")
                     ).values.astype("int64"),
                    np.int64(month_end.value),
                )
            )
            refund_frames.append(pd.DataFrame({
                "refund_id": _seq_ids("R", r_seq, n_fail, 6),
                "order_id": rng.choice(success_ids, size=n_fail),
                "refund_time": rts_f.strftime("%Y-%m-%d %H:%M:%S"),
                "refund_status": "failed",
                "refund_amount": _split_amount(refund_total * 0.12, n_fail, rng),
            }))
            r_seq += n_fail

    orders = pd.concat(order_frames, ignore_index=True)
    refunds = pd.concat(refund_frames, ignore_index=True)
    orders = orders.sort_values("order_id").reset_index(drop=True)
    refunds = refunds.sort_values("refund_id").reset_index(drop=True)
    return orders, refunds


def demo_tables() -> dict:
    """生成干净版演示数据：customers / orders / refunds 三张表。"""
    rng = np.random.default_rng(SEED)
    customers = _make_customers(rng)
    orders, refunds = _make_orders_refunds(rng, customers)
    return {"customers": customers, "orders": orders, "refunds": refunds}


def anomaly_tables(tables: dict | None = None) -> dict:
    """在干净数据上注入异常，供成员 3 测试数据质量检查（分工文档 §5.2.5）。

    :param tables: 可选。传入已生成的表可避免重复生成，显著缩短测试耗时。

    注入的异常类型：
      orders.order_id 重复主键、pay_amount 负数、pay_amount 缺失、
      pay_time 不可解析、customer_id 外键悬空
      refunds.refund_id 重复主键、refund_amount 负数
      customers.customer_name 大面积缺失、删除一个被引用的客户制造孤儿订单
    """
    if tables is None:
        tables = demo_tables()
    orders = tables["orders"].copy()
    refunds = tables["refunds"].copy()
    customers = tables["customers"].copy()

    # 1) 重复主键
    dup = orders.iloc[[10]].copy()
    orders = pd.concat([orders, dup], ignore_index=True)

    # 2) 负金额 + 缺失金额
    orders.loc[orders.index[20], "pay_amount"] = -888.0
    orders.loc[orders.index[21], "pay_amount"] = np.nan
    orders.loc[orders.index[22], "pay_amount"] = 99999999.0  # 异常大额

    # 3) 时间不可解析
    orders.loc[orders.index[30], "pay_time"] = "2026-13-45 99:99:99"

    # 4) 外键悬空
    orders.loc[orders.index[40], "customer_id"] = "C_GHOST_99999"

    # 5) 退款表异常
    refunds = pd.concat([refunds, refunds.iloc[[5]].copy()], ignore_index=True)
    refunds.loc[refunds.index[7], "refund_amount"] = -120.0

    # 6) 客户表大面积缺失
    customers.loc[customers.index[:200], "customer_name"] = np.nan
    customers = customers.drop(index=customers.index[0])  # 删除一个被引用的客户，制造孤儿订单

    return {"customers": customers.reset_index(drop=True),
            "orders": orders.reset_index(drop=True),
            "refunds": refunds.reset_index(drop=True)}


#: 三张表的字段类型声明，供数据质量检查比对（成员 1 的 /datasets/inspect 应返回同结构）
TABLE_SCHEMA = {
    "orders": {
        "primary_key": "order_id",
        "required": ["order_id", "customer_id", "order_time", "pay_time", "pay_status", "pay_amount"],
        "amount_fields": ["pay_amount"],
        "time_fields": ["order_time", "pay_time"],
        "foreign_keys": {"customer_id": "customers.customer_id"},
    },
    "refunds": {
        "primary_key": "refund_id",
        "required": ["refund_id", "order_id", "refund_time", "refund_status", "refund_amount"],
        "amount_fields": ["refund_amount"],
        "time_fields": ["refund_time"],
        "foreign_keys": {"order_id": "orders.order_id"},
    },
    "customers": {
        "primary_key": "customer_id",
        "required": ["customer_id", "region", "customer_type"],
        "amount_fields": [],
        "time_fields": ["register_date"],
        "foreign_keys": {},
    },
}
