# -*- coding: utf-8 -*-
"""数据集注册表：给每次上传分配稳定、可追溯、可复现的数据集版本。

## 补齐了什么

分工文档 §5.2.1 第 1 步「上传业务数据」、§5.2.2 数据接入区「数据版本和更新时间」
这两项目前缺失 —— 页面上的版本号是一个写死的常量，无法区分不同批次的数据。

## 设计要点

1. **版本号由内容哈希生成**，不是时间戳。同一份数据重复上传得到同一个版本号，
   这样「结果依据区」里的数据集版本才是可追溯、可对得上的。
2. **更新时间记录 UTC 时间**，用于区分同一版本号的先后批次。
3. 版本摘要包含行数与字段名，任何一处变化都会导致版本号变化，
   避免「数据偷偷换了但版本号没变」这种最危险的情况。

这直接支撑 §5.4 验收标准：每次成功查询都能查看口径和来源 ——
来源要能对得上，前提就是数据集版本必须是内容感知的。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pandas as pd


def content_signature(tables: dict) -> str:
    """根据三张表的结构 + 内容生成稳定摘要。"""
    h = hashlib.sha256()
    for name in sorted(tables):
        df = tables[name]
        h.update(name.encode("utf-8"))
        h.update(b"\x1f")
        # 结构：列名 + 行数
        h.update("|".join(str(c) for c in sorted(df.columns)).encode("utf-8"))
        h.update(f"|rows={len(df)}".encode("utf-8"))
        h.update(b"\x1f")
        # 内容：取首行、末行与全表数值列求和，兼顾性能与灵敏度
        if len(df):
            h.update(pd.util.hash_pandas_object(df, index=False).values.tobytes())
    return h.hexdigest()


def dataset_version(tables: dict, source: str = "") -> str:
    """生成数据集版本号，例如 `ds-a1b2c3d4e5`。

    :param source: 数据来源标识。内置演示数据与异常测试数据需要区分，
                   因为它们的内容可能接近但语义完全不同。
    """
    sig = content_signature(tables)
    if source:
        sig = hashlib.sha256((source + "|" + sig).encode("utf-8")).hexdigest()
    return f"ds-{sig[:10]}"


def make_record(tables: dict, source: str) -> dict:
    """构造一条数据集注册记录。"""
    return {
        "version": dataset_version(tables, source),
        "source": source,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "tables": {
            name: {"rows": int(len(df)), "cols": int(df.shape[1]),
                   "fields": [str(c) for c in df.columns]}
            for name, df in tables.items()
        },
        "total_rows": int(sum(len(df) for df in tables.values())),
    }


def render_label(record: dict) -> str:
    """侧边栏与下拉框展示用的短标签。"""
    src = record["source"]
    if len(src) > 22:
        src = src[:22] + "…"
    return f"{record['version']} · {src} · {record['total_rows']:,} 行"


def same_tables(a: dict, b: dict) -> bool:
    """两份数据是否完全一致（用于去重，避免重复注册同一批文件）。"""
    return content_signature(a) == content_signature(b)
