# 数桥 DataBridge · 可信取数平台

面向 AI Agent 的可信取数平台。接入结构化业务数据后，通过业务指标定义、自然语言理解、查询计划生成、数据质量检查和结果追溯，为人类用户或其他 AI Agent 提供可靠的数据查询服务。

首版采用零售订单分析场景（订单 / 退款 / 客户）。

> A 赛题 · 团队三人 · 初赛截止 2026-10-14 24:00
> 分工详见 `AI智能体校园黑客松_A赛题_三人分工.md`

---

## 1. 快速开始

### 1.1 安装

```powershell
# 创建虚拟环境（示例路径，可自行替换）
python -m venv .venv

# 安装依赖
.venv\Scripts\python.exe -m pip install -r app/requirements.txt
```

上述仅为页面依赖：`streamlit` 和 `pandas`。运行成员 1 正式后端时另需安装仓库根目录的 `requirements.txt`。

### 1.2 运行

```powershell
.venv\Scripts\python.exe -m streamlit run app/app.py
```

默认打开 `http://localhost:8501`。

**页面开箱可用**：首次运行会自动生成内置演示数据（85,018 条订单），不需要先准备任何数据文件。

### 1.3 启动契约参考服务（联调用，可选）

三人同时开发时互相没有可调用的对象，联调就无从谈起。`app/mock_server.py`
用零第三方依赖把接口契约跑成一个真实 HTTP 服务，**让三方从第一天就能联调**：

```powershell
.venv\Scripts\python.exe app\mock_server.py --port 8000
```

然后把页面切到 live 模式（页面左侧栏切换，或运行前设置环境变量）：

```powershell
$env:DATABRIDGE_BACKEND = "live"
$env:DATABRIDGE_API = "http://127.0.0.1:8000"
```

> 它不是正式后端。成员 1 的 FastAPI 执行层已独立交付；自然语言入口与页面响应仍须在三方联调时逐字段对齐。

### 1.3.1 成员 1 正式执行层与成员 2 智能入口

成员 1 的 SQLite 数据、质检导入、只读查询执行器和 FastAPI 服务已放在仓库根目录的
`data/`、`config/`、`contracts/`、`databridge/`、`scripts/` 中。
它接收**结构化查询计划**，不是自然语言入口。安装根目录 `requirements.txt` 后可独立运行：

```powershell
python scripts/import_dataset.py data/demo --database outputs/demo-v1.0.sqlite3
$env:DATABRIDGE_DATABASE = (Resolve-Path outputs/demo-v1.0.sqlite3).Path
python -m uvicorn databridge.api:app --host 127.0.0.1 --port 8001
```

`POST /v1/query` 是成员 1 的结构化只读执行层；`POST /agent/query` 是成员 2 的自然语言入口，
调用同一个执行层。默认采用可复现的规则解析。可选模型解析需要本机设置
`DATABRIDGE_AGENT_MODE=model`、`OPENAI_API_KEY`、`DATABRIDGE_MODEL`，目前**没有真实模型调用的验证成绩**。
示例运营 Agent 可运行 `python scripts/run_operations_agent.py 生成2026年9月经营简报`。

页面内置 85,018 单的模拟数据与正式后端 20,000 单演示数据不能混用答案或版本；
`/datasets/inspect` 仍未在正式后端实现，页面 live 还不能声称完整联调。
成员 2 的交付和运行/边界见 `docs/member2_delivery.md`；成员 1 的对齐项见
`docs/member1_integration_status.md`，结构化请求样例见 `docs/api_usage.md`。

### 1.4 运行自测

```powershell
.venv\Scripts\python.exe tests\smoke_test.py        # 链路自测，26 项检查
.venv\Scripts\python.exe tests\page_render_test.py  # 页面渲染冒烟测试
.venv\Scripts\python.exe tests\live_mode_test.py    # live 模式 HTTP 全链路，15 项检查
.venv\Scripts\python.exe tests\scenario_test.py     # §5.2.5 八个异常场景，17 项检查
.venv\Scripts\python.exe tests\run_testset.py 开发集  # 测试集自动评分（37 题）
.venv\Scripts\python.exe tests\run_testset.py 保留集  # 只读基线检查（最终测试才正式跑）
.venv\Scripts\python.exe tests\formal_dataset_test.py # 正式库 demo-v1.0 × 页面管线一致性（35 项）
.venv\Scripts\python.exe tests\run_experiment.py      # S1 vs S2 对照实验（37 题 × 2 方案）
.venv\Scripts\python.exe tests\is001_refund_timing.py # IS-001 退款时间归属两口径对比
.venv\Scripts\python.exe tests\export_showcase_data.py  # 导出展示页数据
```

输出同时写入各脚本对应的 `_*_out.txt`，例如 `tests/_smoke_out.txt`、`tests/_live_out.txt`。

---

## 2. 目录结构

```
.
├── README.md                          本文件：安装与运行说明
├── AI智能体校园黑客松_A赛题_三人分工.md    团队分工主文档
│
├── shared/
│   └── contracts.py                   ★ 三方共享接口契约（唯一事实来源）
├── app/
│   ├── app.py                         Streamlit 产品页面（成员 3 主责）
│   ├── client.py                      后端适配层：mock / live 双模式
│   ├── config.py                      运行配置
│   ├── mock_backend.py                页面侧参考实现（解析 + 执行）
│   ├── mock_server.py                 契约参考服务：把参考实现暴露成 HTTP
│   ├── demo_data.py                   演示数据与异常数据生成
│   ├── dataset_registry.py            数据集注册：内容哈希版本号
│   ├── quality.py                     数据质量检查（对照实现）
│   └── requirements.txt
├── docs/
│   ├── 接口契约补充_v1.1_澄清与异常结构.md
│   ├── 测试集与对照实验说明.md
│   └── 成员3交付说明_20260930.md
└── tests/
    ├── 测试题_开发集_30题.csv
    ├── 测试题_开发集_补充回归7题.csv
    ├── 测试题_保留集_30题.csv
    ├── 对照实验记录表.csv              37 题 × 2 方案 = 74 行
    ├── build_experiment_sheet.py      从开发集生成实验记录表（空表）
    ├── s1_baseline.py                 S1 基线：只看表结构的直接 Text-to-SQL 行为模拟
    ├── run_experiment.py              S1 vs S2 对照实验执行器（填表 + 数值核对 + 归因）
    ├── is001_refund_timing.py         IS-001 退款时间归属两口径对比（跨月退款变体）
    ├── _对照实验明细.csv               74 行逐题明细（含实际数值与差异归因）
    ├── _IS001口径对比.csv              月份×地区两口径净销售额差异表
    ├── export_showcase_data.py        导出展示页所需的真实计算结果
    ├── run_testset.py                 测试集自动评分器
    ├── scenario_test.py               §5.2.5 八个异常场景（F01~F08）
    ├── smoke_test.py                  链路自测（26 项，含退款不超额/无孤儿退款）
    ├── page_render_test.py            页面渲染冒烟测试
    └── live_mode_test.py              live 模式 HTTP 全链路（15 项）
```

---

## 3. Git 协作规范（分工文档 §9.3）

### 3.0 分支与提交

| 约定 | 规则 |
|---|---|
| 主分支 | `main`，始终保持**可运行** |
| 功能分支 | `feat/<模块>-<简述>`，例如 `feat/backend-query-executor` |
| 修复分支 | `fix/<编号>-<简述>`，例如 `fix/D13-customer-count-synonym` |
| 合并 | 至少由另一名成员检查后再合入 `main` |

提交信息前缀：`feat` / `fix` / `docs` / `test` / `refactor` / `chore`。

### 3.1 每日提交（硬性要求）

分工文档 §9.3：**每天结束前将可运行代码提交到共享仓库。**
当日交付必须是可检查的产物（可调用的接口、可运行的页面、有结论的测试记录），
不接受「正在学习」「正在写代码」作为当日交付。

### 3.2 敏感信息

- API 密钥**不得**提交到仓库（`.gitignore` 已排除 `.env`、`config.local.py`）
- 确需配置时使用环境变量，见 `app/config.py`

### 3.3 常用命令

```powershell
git switch -c feat/your-module          # 开分支
git add -A
git commit -m "feat: 一句话说明改了什么"
git switch main && git merge feat/your-module
git push
```

> 没有远端仓库时，三人无法真正同步。需要一名成员创建远端后把地址发给另外两人：
> `git remote add origin <地址>` 然后 `git push -u origin main`。

---

## 4. 三方如何对接

### 3.1 成员 1（数据与后端）

共享契约目标接口如下；成员 1 当前已交付结构化执行接口 `/v1/query`，其与这些对外接口的联调状态见 `docs/member1_integration_status.md`：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| POST | `/agent/query` | 自然语言取数，含澄清二次提交 |
| POST | `/datasets/inspect` | CSV 上传与数据质量检查 |

**所有枚举取值必须从 `shared/contracts.py` import，不要另写字面量。**

对照实现 `app/mock_backend.py` 可直接用作数值基准：给同一订单追加 5 条 1000 元退款，净销售额应精确下降 5000 元，实付金额不变。

### 3.2 成员 2（AI Agent 与智能流程）

- 输出的结构化查询计划字段名见 `contracts.PLAN_KEYS`。
- 澄清响应结构见 `contracts.CLARIFICATION_TEMPLATE`；`id` 必须遵循 `clr_<target_field>_<三位序号>`。
- 最多澄清 2 轮（`contracts.MAX_CLARIFICATION_ROUNDS`），超过必须降级为 `insufficient_data`。
- 歧义词表见 `contracts.AMBIGUOUS_METRIC_TERMS`，命中必须澄清，不得使用默认口径直接回答。

### 3.3 成员 3（产品前端与测试交付）

页面默认 `mock` 模式。成员 1 服务上线后，在页面左侧栏把后端模式切到 `live` 并填写服务地址即可，**无需改动任何页面代码**。

也可以在运行前指定：

```powershell
$env:DATABRIDGE_BACKEND = "live"
$env:DATABRIDGE_API = "http://127.0.0.1:8000"
```

---

## 5. 页面功能区域

| 标签页 | 内容 |
|---|---|
| ① 数据接入 | 文件上传、数据集列表、字段类型、质量问题（逐条带影响说明）、数据版本 |
| ② 业务字典 | 指标口径与公式、单位、同义词、维度、表关系、歧义词表、已冻结字段 |
| ③ 智能取数 | 自然语言输入、对话记录、澄清交互、结果表与图表、10 条快捷示例 |
| ④ 结果依据 | 口径、来源表、时间与筛选、数据集版本、查询记录 SQL、质量警告 |
| ⑤ Agent 调用回放 | 示例运营 Agent 的完整调用过程、结果、分析与限制说明 |

---

## 6. 展示材料

| 文件 | 用途 |
|---|---|
| `docs/演示脚本大纲.md` | 答辩与演示视频脚本：10 分钟分镜、5 分钟精简版、可念数字对照表、评委问答预案 |
| `docs/产品展示页.html` | 静态展示页，用于答辩、PPT 截图、演示视频封面。浏览器直接打开即可 |
| `docs/展示数据.json` | 展示页所用的数据，由 `tests/export_showcase_data.py` 从平台真实计算导出 |
| `docs/测试集与对照实验说明.md` | 测试集分类、判定规则与实验执行方法 |
| `docs/派生指标设计草案_v0.1.md` | 退款率/客单价/支付人均消费的契约草案（待三人 10-08 前确认，未改现有行为） |
| `docs/联调数据集统一方案_DS-001.md` | 两套演示数据的差异量化、地区词表三选项与统一落地清单（待三人确认） |

展示页**不替代**可运行产品，它只是让评委在 30 秒内看懂产品价值。
重新生成展示数据：

```powershell
.venv\Scripts\python.exe tests\export_showcase_data.py
```

硬性原则：展示页上的每个数字都必须来自平台真实计算，不得手写
（分工文档 §10、§5.4）。

---

## 7. 数据与口径说明

- 内置演示数据为**模拟业务数据**，生成方法见 `app/demo_data.py`。订单量 85,018 条，覆盖 2026-06-01 ~ 2026-09-30。
- 实付金额与成功退款金额的月度、地区总量由配置精确控制，因此环比结论稳定可复现；订单数与客户数由实际生成的行推导。
- 订单表内故意混入 `failed` / `pending` / `cancelled` 订单，退款表内混入 `failed` 退款。**这些行不参与任何指标统计。**
- 勾选「载入异常测试数据集」可切换到注入了重复主键、缺失值、负金额、脏时间、悬空外键的数据，用于验证数据质量检查能力。
- `demo_data.cross_month_refund_tables()` 提供独立的**跨月退款变体**：把华东 8 月订单的 5 笔成功退款（2,520.54 元）移到 9 月，用于 IS-001 退款时间归属口径决策（`tests/is001_refund_timing.py`）。它不修改干净数据，基线数字不受影响。
- 业务基准日：`2026-09-30`；数据集版本：`mock-v1.0-demo`。

---

## 8. 当前限制

1. 页面默认仍使用页面侧参考实现；成员 1 正式查询服务已并入源码，但自然语言入口、数据上传与统一数据集尚未完成三方联调。
2. 示例运营 Agent 为页面侧调用回放，正式 Agent 由成员 2 交付。
3. 首版仅支持 5 个基础指标，不支持退款率、客单价等派生比率指标（派生指标契约草案已出，见 `docs/派生指标设计草案_v0.1.md`，待三人确认后实现）。
4. 净销售额中「同期成功退款金额」的时间归属口径待三人确认（议题 IS-001，截止 10-08）；成员 3 已用跨月退款变体完成两口径对比实验并给出推荐结论（按 refund_time 归属），见 `docs/测试集与对照实验说明.md` §4 与 `tests/_IS001口径对比.csv`。
5. 演示数据为模拟数据，任何结论都不代表真实经营情况。
