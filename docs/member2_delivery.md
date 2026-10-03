# 成员 2：智能取数与运营 Agent 交付说明（2026-10-02）

本分支在成员 1 的 `feat/member1-backend-integration` 之上，实现成员 2 的独立 AI 工作流。**已用成员 1 正式演示库验证规则模式；未用真实模型密钥调用或评测模型模式；页面上传/激活正式数据集仍未联通。**

## 已完成

1. `agent/workflow.py`：自然语言解析、同义词、时间和维度筛选、指标歧义澄清（最多两轮）、不可回答问题拒答、共享查询计划、执行层映射、金额“分→元”转换、结果解释与追溯。
2. `agent/model.py`、`agent/prompts/plan_v1.txt`：可选的 OpenAI Responses JSON 模式调用。模型**只提出槽位**，不接触数据库、不生成可执行 SQL、不输出业务数字。槽位经过白名单校验；格式异常返回 `model_output_invalid`，服务不可用返回 `execution_failed`。提示词有版本号。
3. `POST /agent/query`：成员三页面约定的自然语言入口，调用成员一原有的只读 `QueryService`；`POST /v1/query` 保持结构化执行层原样。
4. `agent/operations.py` 与 `scripts/run_operations_agent.py`：示例运营 Agent，查询某月各地区净销售额和环比，按成员三展示口径以**环比下降百分比**找降幅最大的地区，同时列出对应减少金额，生成简报并附口径、来源、版本、查询号和限制。
5. 修复 `shared/contracts.py` 中 `clr_date_range_001` 不能反解为 `date_range` 的错误，保障两轮澄清闭环。

## 可复现运行

在仓库根目录安装根目录 `requirements.txt` 后：

```powershell
python scripts/import_dataset.py data/demo --database outputs/demo-v1.0.sqlite3
$env:DATABRIDGE_DATABASE = (Resolve-Path outputs/demo-v1.0.sqlite3).Path
python -m uvicorn databridge.api:app --host 127.0.0.1 --port 8001
```

向 `http://127.0.0.1:8001/agent/query` 发 JSON 请求：

```json
{"question":"2026年9月各地区净销售额环比"}
```

示例运营 Agent：

```powershell
python scripts/run_operations_agent.py 生成2026年9月经营简报
```

默认 `DATABRIDGE_AGENT_MODE=rules`，不需要模型密钥。如要试验模型解析，在**本机环境变量**中设置 `DATABRIDGE_AGENT_MODE=model`、`OPENAI_API_KEY`、`DATABRIDGE_MODEL`。不要把密钥写入代码、文档、提交或截图。模型模式尚未使用真实账户验证，不能称为模型实测通过。模型接口的 JSON 模式和 Responses 结构依据 [OpenAI 官方文档](https://developers.openai.com/api/docs/guides/structured-outputs)；即使返回合法 JSON，系统仍自行验证指标、时间和维度，最终数字只来自成员一服务。

## 测试与真实边界

`tests/member2_workflow_test.py` 包含正式库数值核对、HTTP 入口、两轮澄清、上下文隔离、模型失败/格式异常、环比及示例 Agent。成员三的 **37 道开发题**只做状态核对，不用页面模拟数据答案与正式库数值交叉评分。其中 35 道状态与页面原预期一致，2 道因数据集不同而合理不同：

- D10“上个月西南地区实付金额”：页面模拟数据有“西南”，正式库没有，正式入口返回 `insufficient_data`，而不是偷偷转成“西部”。
- D24“2026 年 3 月净销售额”：页面模拟数据只覆盖 6–9 月，正式库覆盖 1–9 月，因此正式入口可以返回 `success`。

正式库结果中有“西部”，但共享枚举目前只有“华东、华南、华北、西南、华中”；对外结果会保留实际“西部”并给出 `contract_region_mismatch` 警告。不能将两套数据集数字或评测结论混用。

**尚待三人联调/确认**：

- 页面当前仍会把内置页面数据的 `ds-...` 版本传给 live 入口；正式入口会明确拒绝，避免把正式库结果贴到页面模拟数据版本下。需要成员三实现正式数据集选择/激活路径。
- `/datasets/inspect` 仍只有参考服务版本，正式后端未实现上传/激活；成员一、三需共同确认流程。
- 地区枚举及客户类型标签与正式库不一致；当前入口对客户类型做明确映射，对不支持的地区明确拒绝，对结果出现的“西部”加警告。是否统一数据还是修改共享枚举必须由三人确认。
- IS-001 退款月份归属仍待三人最终确认。当前正式计算和参考实现均按退款完成时间归属。
- 模型模式真实调用与准确率、成本、时延尚未测量；不能把规则模式测试成绩写成大模型实验成绩。

合并顺序：先审查/合并成员一分支，再将本分支的成员二增量合并到 `main`。本分支不直接改动 `main`。
