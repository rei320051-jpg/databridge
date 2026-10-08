# -*- coding: utf-8 -*-
"""一键生成赛题二「最终提交包」zip（可复现、零密钥）。

纳入：git HEAD 全部受跟踪文件（git ls-files，天然不含 .env/.venv/缓存）
      ＋ 预构建的 outputs/demo-v1.1.sqlite3、outputs/small-v0.1.sqlite3（开箱可跑）
      ＋ 自动生成的《提交清单.md》《SHA256SUMS.txt》。
排除：.env 等任何密钥文件、虚拟环境、__pycache__、dist 目录本身。

安全闸：
  1. git 工作区必须干净（包内容 == 某个已提交的 HEAD）；
  2. 文件名黑名单（.env / *.env 等）；
  3. 对全部文本条目扫描密钥形态（sk-xxxx），命中即中止。

用法：
    python scripts/build_submission.py            # 输出 dist/DataBridge_最终提交包_YYYYMMDD.zip
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import subprocess
import zipfile
from contextlib import closing
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from databridge.importer import PRIMARY_KEYS, TABLE_FIELDS, QualityAudit

PREBUILT_DBS = ["outputs/demo-v1.1.sqlite3", "outputs/small-v0.1.sqlite3"]
FORBIDDEN_NAMES = {".env"}
FORBIDDEN_SUFFIX = (".env",)
SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9]{20,}")
TEXT_HINT = (".py", ".md", ".txt", ".json", ".csv", ".html", ".sql", ".gitattributes",
             ".gitignore", ".lock", ".schema")

TODAY = date.today().strftime("%Y%m%d")
PKG_DIR = f"DataBridge_最终提交包_{TODAY}"
ZIP_PATH = ROOT / "dist" / f"{PKG_DIR}.zip"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=True).stdout


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_prebuilt_database(database: Path, source: Path) -> None:
    """Refuse stale/corrupt ignored databases, even if their version and size match."""
    audit = QualityAudit(source)
    report = audit.run()
    if report['error_count']:
        raise SystemExit(f'源 CSV 质检失败：{source}')
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
            connection.execute('PRAGMA query_only=ON')
            if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('integrity check failed')
            if connection.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('foreign key check failed')
            meta = audit.metadata
            expected = [(meta['dataset_version'], int(meta['is_simulated']), meta['timezone'],
                         meta['coverage_start'], meta['coverage_end_exclusive'])]
            if connection.execute('SELECT * FROM dataset_metadata').fetchall() != expected:
                raise ValueError('metadata mismatch')
            for table, fields in TABLE_FIELDS.items():
                expected = sorted(tuple(row[field] for field in fields) for _, row in audit.rows[table])
                actual = connection.execute(f"SELECT {','.join(fields)} FROM {table} ORDER BY {PRIMARY_KEYS[table]}").fetchall()
                if actual != expected:
                    raise ValueError(f'{table} content mismatch')
            warnings = connection.execute('SELECT code, message, table_name, row_number, field_name FROM data_quality_issues ORDER BY issue_id').fetchall()
            expected = [(item['code'], item['message'], item.get('table'), item.get('row'), item.get('field'))
                        for item in report['issues'] if item['severity'] == 'warning']
            if warnings != expected:
                raise ValueError('quality warnings mismatch')
    except (sqlite3.Error, OSError, ValueError) as exc:
        raise SystemExit(f'预构建库无效或与源 CSV 不一致：{database.name}（{exc}），请用导入脚本重新构建') from None


def collect_entries(commit: str) -> dict[str, bytes]:
    """arcname(相对包根) -> 文件字节。"""
    tracked = [p for p in git("ls-files", "-z").split("\0") if p]
    entries: dict[str, bytes] = {}
    for rel in tracked:
        name = Path(rel).name
        if name in FORBIDDEN_NAMES or rel.endswith(FORBIDDEN_SUFFIX):
            raise SystemExit(f"[安全闸] 受跟踪文件命中密钥黑名单，已中止：{rel}")
        if rel.startswith("dist/"):
            raise SystemExit(f"[安全闸] dist 产物不应受版本跟踪：{rel}")
        entries[rel] = (ROOT / rel).read_bytes()

    for rel in PREBUILT_DBS:
        db = ROOT / rel
        if not db.is_file():
            raise SystemExit(f"缺少预构建库 {db}，请先运行 scripts/import_dataset.py（见 README）")
        source = ROOT / 'data' / ('demo' if db.name.startswith('demo-') else 'small')
        validate_prebuilt_database(db, source)
        entries[rel] = db.read_bytes()

    # 密钥内容扫描（仅文本形态文件；sqlite 为二进制不参与）
    for rel, data in entries.items():
        if Path(rel).suffix.lower() in TEXT_HINT or Path(rel).name in (".gitignore", ".gitattributes"):
            try:
                text = data.decode("utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                continue
            if SECRET_PATTERN.search(text):
                raise SystemExit(f"[安全闸] 在 {rel} 中检测到疑似 API Key，已中止（密钥不得入包）")
    print(f"[1/4] 收集 {len(entries)} 个文件（含 {len(PREBUILT_DBS)} 个预构建库），HEAD={commit[:8]}")
    return entries


def build_manifest(commit: str, n_files: int) -> str:
    return f"""# 数桥 DataBridge · 赛题二最终提交清单

> 生成日期：{date.today().isoformat()}　·　代码版本：`{commit}`　·　文件数：{n_files}
> 对应赛事：数联科技 × 华东师范大学 AI 智能体校园黑客松 · 赛题二（A：AI 使用的大数据平台方向）
> 初赛提交截止：2026-10-14 24:00（DataClawHub 赛事专区线上提交）
> PPTX 由 scripts/build_pptx.mjs 生成（需 Node.js：`npm --prefix outputs/_pptx install pptxgenjs` 后 `node scripts/build_pptx.mjs`）

## 一、赛题二最低交付物对照

| 赛事要求（赛事执行方案 P3） | 本包对应材料 |
|---|---|
| 问题与方案（目标用户 / 痛点 / 场景 / 技术路线 / 数据来源 / 预期价值） | `README.md`、`AI智能体校园黑客松_A赛题_三人分工.md`、`docs/答辩PPT初稿.md`、`docs/data_dictionary.md` |
| 交付成果：可运行的 AI 智能体 / 轻量应用原型（允许模拟数据） | Streamlit 产品页 `app/app.py`；FastAPI 只读查询服务 `databridge/`；自然语言 Agent `agent/`；模拟数据集 `data/demo/`（2 万订单 / 2026-01~09） |
| 验证材料（输入、输出、关键指标、已知限制） | `docs/测试报告.md`（§4 实验结论 / §5 缺陷登记 / §6 结论与限制）、`docs/测试集与对照实验说明.md`、`tests/_评测结果_*.csv`、`tests/_LLM真实模型复测明细.csv`、`tests/_对照实验记录表_formal.csv` |
| 路演展示（≤5 分钟演示视频或现场演示）＋使用说明 | `docs/答辩幻灯片.pptx`（17 页可编辑 PowerPoint，PptxGenJS 由 `scripts/build_pptx.mjs` 生成）、`docs/答辩幻灯片.html`（浏览器直接放映）、`docs/演示脚本大纲_formal.md`；使用说明见 `docs/产品使用说明.md`。**演示视频待录制**（亦可采用现场演示） |

## 二、目录速览

- `app/`：Streamlit 产品页面与 mock 参考服务（成员 3）
- `databridge/`：FastAPI 结构化只读执行层、质检导入器（成员 1）
- `agent/`：自然语言工作流、规则/真实大模型双模式槽位解析、派生比率组合（成员 2）
- `shared/contracts.py`：三模块唯一事实来源（指标 / 状态 / 维度 / 枚举，v1.2 冻结口径）
- `data/demo/`、`data/small/`：演示与最小数据集 CSV（含 manifest 与 expected）
- `outputs/*.sqlite3`：已按 CSV 预构建的正式库与最小库，**免导入即可启动**
- `tests/`：16 个自动化回归入口、37+30 题评分集、S1/S2 对照与真实模型复测证据
- `docs/`：使用说明、测试报告、数据字典、口径冻结确认单、答辩材料

## 三、三分钟启动（默认离线规则模式，无需任何 API 密钥）

```powershell
python -m venv .venv
.venv\\Scripts\\python.exe -m pip install -r app/requirements.txt -r requirements.txt

# 产品页面（内置 85k 模拟数据，开箱即用）
.venv\\Scripts\\python.exe -m streamlit run app/app.py
```

正式后端 + 自然语言 Agent（预构建库已随包提供，导入步骤可跳过）：

```powershell
.venv\\Scripts\\python.exe -m uvicorn databridge.api:app --host 127.0.0.1 --port 8001
# 健康检查：GET http://127.0.0.1:8001/health
# 必须显示 status=ok、dataset_version=demo-v1.1、orders=20000；默认读取正式演示库。
# 页面侧选择 live、地址 http://127.0.0.1:8001、数据源「正式联调库 demo-v1.1」。
# 若终端残留 DATABRIDGE_DATABASE，请显式设为本包的正式库：
# $env:DATABRIDGE_DATABASE = (Resolve-Path outputs/demo-v1.1.sqlite3).Path
# 自然语言：POST http://127.0.0.1:8001/agent/query  body: {{"question":"2026年9月净销售额"}}
# 重新建库（可选）：
# .venv\\Scripts\\python.exe scripts/import_dataset.py data/demo --database outputs/demo-v1.1.sqlite3
```

（可选）启用真实 DeepSeek：在仓库根目录自建已被 git 忽略的 `.env`
（`OPENAI_API_KEY` / `DATABRIDGE_MODEL=deepseek-flash` / `DATABRIDGE_BASE_URL=https://api.deepseek.com`），
并设 `DATABRIDGE_AGENT_MODE=model`；方法详见 `docs/产品使用说明.md`。**密钥不在本包内。**

## 四、复现实验与测试（成果可复现性）

```powershell
.venv\\Scripts\\python.exe tests/smoke_test.py                 # 链路 26 项
.venv\\Scripts\\python.exe tests/run_testset.py 开发集         # 37/37
.venv\\Scripts\\python.exe tests/run_testset.py 保留集         # 30/30
.venv\\Scripts\\python.exe tests/run_experiment.py --source formal   # S1 0/37 vs S2 37/37
.venv\\Scripts\\python.exe tests/run_llm_testset.py --channel rules --set all  # 真实模型复测的离线预检
# 真实模型全量复测（需自有密钥）：tests/run_llm_testset.py --channel both --set all
```

关键结论（2026-10-06 实测，全部可由上方命令重算）：

- 同一问题 S1 报 18,166,729.12 元，真值 17,198,835.91 元，虚高 967,893.21 元；S2 开发集 37/37、保留集 30/30。
- 真实 DeepSeek 全量复测 67 题，与离线规则 67/67 逐字段一致、0 编造；54 题调用模型、13 题护栏前零调用；平均 0.93s、实付约 ¥0.023。
- 退款按退款完成月归属（IS-001 方案 A，三人 2026-10-06 签字冻结）；跨月退款占比 44.28%。

## 五、已知限制（如实声明，详见测试报告 §6）

固定种子模拟数据不代表真实经营；真实模型仅验证单一供应商（deepseek-flash）与 67 道零售题；
"LLM 直接生成 SQL"不在产品架构内（模型不接触数据库，S1 保留为确定性对照）；
首版 2 维度、5+3 指标，同比/预测/因果/复购率不做。

## 六、完整性校验

发布包内附 `SHA256SUMS.txt`。解压后在包根目录执行，输出「全部校验通过」即完整：

```powershell
.venv\\Scripts\\python.exe -c "import hashlib,pathlib;bad=[l for l in open('SHA256SUMS.txt',encoding='utf-8') if hashlib.sha256(pathlib.Path(l.split()[1]).read_bytes()).hexdigest()!=l.split()[0]];print('全部校验通过' if not bad else bad)"
```
"""


def main() -> int:
    dirty = git("status", "--porcelain").strip()
    if dirty:
        raise SystemExit("[安全闸] git 工作区不干净，请先提交改动（仅暂存不够），保证提交包 == 已提交版本：\n" + dirty)
    commit = git("rev-parse", "HEAD").strip()

    entries = collect_entries(commit)
    manifest = build_manifest(commit, len(entries) + 2)
    entries["提交清单.md"] = manifest.encode("utf-8")

    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    # 先写除校验文件外的全部条目，再统一生成 SHA256SUMS
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in sorted(entries):
            zf.writestr(f"{PKG_DIR}/{rel}", entries[rel])
        lines = []
        for rel in sorted(entries):
            lines.append(f"{sha256_bytes(entries[rel])}  {rel}")
        zf.writestr(f"{PKG_DIR}/SHA256SUMS.txt", ("\n".join(lines) + "\n").encode("utf-8"))

    # 回读校验：可打开、无密钥文件、条目数正确、testzip 无坏块
    with zipfile.ZipFile(ZIP_PATH) as zf:
        bad = zf.testzip()
        if bad:
            raise SystemExit(f"zip 损坏：{bad}")
        names = zf.namelist()
        if any(Path(n).name in FORBIDDEN_NAMES or n.endswith(FORBIDDEN_SUFFIX) for n in names):
            raise SystemExit("[安全闸] zip 内出现密钥文件名，已中止")
        must_have = [f"{PKG_DIR}/提交清单.md", f"{PKG_DIR}/SHA256SUMS.txt",
                     f"{PKG_DIR}/outputs/demo-v1.1.sqlite3", f"{PKG_DIR}/app/app.py",
                     f"{PKG_DIR}/docs/答辩幻灯片.html"]
        for m in must_have:
            if m not in names:
                raise SystemExit(f"zip 缺少关键文件：{m}")
        for rel, data in entries.items():
            if sha256_bytes(zf.read(f'{PKG_DIR}/{rel}')) != sha256_bytes(data):
                raise SystemExit(f'zip 回读 SHA256 失配：{rel}')

    size_mb = ZIP_PATH.stat().st_size / 1024 / 1024
    print(f"[2/4] 已生成《提交清单.md》与 SHA256SUMS.txt（{len(entries)} 个文件参与校验）")
    print(f"[3/4] 回读校验通过：testzip 无坏块、无密钥文件、关键文件齐全")
    print(f"[4/4] 输出：{ZIP_PATH.relative_to(ROOT)}（{size_mb:.2f} MB，zip 内 {len(names)} 个条目）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
