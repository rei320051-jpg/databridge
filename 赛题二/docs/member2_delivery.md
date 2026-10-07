# 成员二智能流程交付（2026-10-05）

基线 main `83c9f40`；分工 §4 对应模块已在独立功能分支补齐。规则模式、正式只读执行层及真实 HTTP 运营 Agent 已验证。模型接口仅做协议与失败测试，未进行真实模型调用。

## 现有成果与本次补齐

原实现已有五个基础指标、规则/模型双模式、两轮澄清、正式库执行与本地简报。本次补齐：

| 模块 | 产物与行为 |
|---|---|
| 问题理解 | `agent/workflow.py`：八个共享指标及同义词、地区/客户类型筛选分组、明确排名、环比降幅排序；模糊指标和人均消费提出具体澄清 |
| 时间 | `agent/periods.py`：阿拉伯/中文年月、完整日期区间、季度、最近明确天数、今天/昨天/前天；参考日固定为共享 `2026-09-30`，不使用电脑当前日期 |
| 澄清 | 日期、维度、筛选、排序、环比、排名条件跨轮保留；新问题隔离上下文；最多两轮，失败不产生数字 |
| 派生指标 | `agent/derived.py`：同源同期同筛选同分组查询分子分母，先聚合再除；退款率按百分数保留两位，金额平均值按元保留两位；零分母为 null + 警告 |
| 模型 | `agent/model.py` + `agent/prompts/plan_v2.txt`：Responses JSON 模式；共享指标定义/单位、参考日期、表字段及关系进入上下文；合法 JSON 仍须本地字段/枚举/日期验证 |
| 异常与拒答 | 写操作、预测、因果、未知比率、同比及不支持的任意两期比较明确失败；缺少基期的增长率不伪装成基础指标查询；日期错误、模型结构错误与网络失败返回六态契约中的对应状态 |
| 运营 Agent | `agent/client.py`、`agent/operations.py`、`scripts/run_operations_agent.py`：本地调用或 `--api` 真实 HTTP；接口结果缺少环比字段、截断、无结果时不生成完整经营简报 |

### 派生查询与成员一边界

成员一 `/v1/query` 仍接受五个基础指标，机器契约 `contracts/query_plan.schema.json` 不改。自然语言 `/agent/query` 在 Agent 层组合两个已支持的基础查询，支持共享 v1.2 的三个比率；不是成员一原生单 SQL 比率接口。

每行返回 `numerator_value` / `denominator_value`；环比附 `compare_numerator_value` / `compare_denominator_value`。信封带 `metric_kind=ratio`、`components` 和 `component_query_ids`。`query_id` 指向分子基础查询记录，完整派生依据必须同时读取两项 `component_query_ids`。显示 SQL/参数同时包括两份基础记录。任一分量失败、追溯失败、截断或计算期间数据库文件改变均不返回派生数字。正式导入器禁止覆盖现有库；演示时固定已导入文件，不在查询期间外部替换数据库。

## 启动与演示

PowerShell，在仓库根目录：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts/import_dataset.py data/demo --database outputs/demo-v1.1.sqlite3
$env:DATABRIDGE_DATABASE = (Resolve-Path outputs/demo-v1.1.sqlite3).Path
$env:DATABRIDGE_AGENT_MODE = "rules"
.venv\Scripts\python.exe -m uvicorn databridge.api:app --host 127.0.0.1 --port 8001
```

导入器拒绝覆盖已有文件；已有已验证数据库时跳过导入。在另一终端运行：

```powershell
.venv\Scripts\python.exe scripts/run_operations_agent.py --api http://127.0.0.1:8001 "生成2026年9月经营简报"
```

真实正式库演示结论：华南净销售额 4,105,228.89 元，环比下降 15.72%，减少 765,507.42 元。均由平台计算，模拟数据不能代表真实经营，不推断原因。脚本成功退出 0；无法生成简报退出 2。

自然语言示例：`2026年9月各地区退款率`、`2026年9月新客户各地区客单价`、`2026年9月人均消费`（澄清）、`2026-09-01至2026-09-30实付金额`。

## 接口对接

请求仍为 `question`、可选 `dataset_version`、`context`、`clarification`。澄清必须回传上次 `context` 或 `clarification.resolved_context`，并提供 `clarification.id` 和 `choice`/`free_text`；指标澄清可直接发送简短选项，不需重复原问题。支持的比较编码仍为 `none` / `mom`。Top N、降幅排名附加输出 `ranking_limit` / `ranking_basis`，不改变七个共享计划键。

示例：

```json
{"question":"2026年9月各地区退款率","dataset_version":"demo-v1.1"}
```

前端字段仍从 `shared/contracts.py` 取；金额已转换为元，退款率输出百分数（12.28 表示 12.28%），增长率仍为小数。不能把页面 85k 模拟库和正式 20k 库的版本与答案混用。

## 复现验收

```powershell
.venv\Scripts\python.exe scripts/import_dataset.py data/small --database outputs/small-v0.1.sqlite3
.venv\Scripts\python.exe -m unittest discover -s tests -p "member2*test.py" -v
.venv\Scripts\python.exe scripts/test_query_api.py
.venv\Scripts\python.exe scripts/test_importer.py
.venv\Scripts\python.exe scripts/validate_demo.py
```

成员二测试 34 项（原 11 + 新 23），含 37 道开发题的状态核对、独立 SQL 数值、两轮澄清、拒答、畸形模型响应、真实 HTTP/CLI 与断网。不同库导致 D24（3月）在正式入口可成功，不能把开发题状态通过声称为大模型准确率。保留集未用于调试。

后端查询 17 项、导入 7 项、正式库 70 个独立期望值检查通过；页面派生指标回归和正式库页面管线一致性验证通过。测试记录及审查结论见 `docs/member2_validation_2026-10-05.md`。依赖中的 Starlette/httpx TestClient 弃用提示来自原仓库锁定依赖，不影响本次真实 HTTP 验证。

## 已知限制与交接

- 未配置模型密钥与模型名称，未测真实调用、准确率、成本和时延。模型输出格式错返回 `model_output_invalid`，服务错返回 `execution_failed`；由调用方按 `retryable` 重试或显式切规则模式，不静默回退。协议参考 [OpenAI 官方 JSON 模式说明](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)。
- 同比和任意两期比较未进入冻结的自然语言比较枚举，明确拒答并建议分别查询；结构化执行层本身支持显式 compare。
- `/datasets/inspect` 与正式库页面上传/激活仍需成员一、三交接，本次不修改页面或上传接口。
- 规则解析支持已说明的表达，不保证任意自然语言。结论仅针对模拟库，不包含因果与预测。
- 本次未代签三人确认单，未发送团队消息；以 PR 和文档提供可复核变更，由团队按流程审查合入 main。
