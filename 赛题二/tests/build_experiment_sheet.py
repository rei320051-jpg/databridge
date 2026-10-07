# -*- coding: utf-8 -*-
"""从开发测试集生成对照实验记录表（分工文档 §5.2.4）。

目的：避免手工抄录造成题号、问题文本与测试集不一致。
生成结果：tests/对照实验记录表.csv
  每行 = 一道题 × 一种方案（基础方案 / 完整方案）
  需要填写的列：实际状态、是否正确回答、是否正确澄清、是否无依据编造、
                是否完成、响应时间、模型调用次数、token消耗
"""

from __future__ import annotations

import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEV = [HERE / "测试题_开发集_30题.csv",
       HERE / "测试题_开发集_补充回归7题.csv"]
OUT = HERE / "对照实验记录表.csv"

SCHEMES = [
    ("S1", "基础方案：大模型根据表结构直接生成 SQL"),
    ("S2", "完整方案：业务字典 + 查询计划 + 歧义澄清 + 结果检查"),
]

FILL = ["实际状态", "是否正确回答", "是否正确澄清", "是否无依据编造",
        "是否完成", "响应时间(秒)", "模型调用次数", "token消耗", "备注"]

HEADER = ["实验编号", "方案编号", "方案说明", "题号", "问题", "分类",
          "预期状态", "是否需澄清", "是否应拒答"] + FILL


def main() -> None:
    rows = []
    for src in DEV:
        if not src.exists():
            continue
        with open(src, encoding="utf-8-sig", newline="") as fh:
            rows.extend(csv.DictReader(fh))

    lines = []
    with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        for scheme_id, scheme_desc in SCHEMES:
            for r in rows:
                w.writerow([
                    "EXP-20261009",
                    scheme_id,
                    scheme_desc,
                    r["题号"],
                    r["问题"],
                    r["分类"],
                    r["预期状态"],
                    r["是否需澄清"],
                    r["是否应拒答"],
                    "", "", "", "", "", "", "", "", "",
                ])
                lines.append(f"{scheme_id} {r['题号']}")

    print(f"rows={len(lines)} -> {OUT}")


if __name__ == "__main__":
    main()
