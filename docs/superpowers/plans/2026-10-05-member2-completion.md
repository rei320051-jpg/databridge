# Member 2 Completion Implementation Plan

> Agentic workers: execute inline with executing-plans; use requesting-code-review for an independent final review.

**Goal:** 完成分工 §4 的正式 AI 工作流和运营 Agent，并对齐现有 v1.2 契约。

**Architecture:** 规则解析校验后调用成员一只读服务；派生指标组合两份已有聚合结果；HTTP 客户端调用同一自然语言入口。

**Tech Stack:** Python、FastAPI、SQLite、unittest、urllib。

## Global Constraints

- 不改冻结字段名和成员一 /v1/query 契约，不改成员三页面。
- 不使用保留测试题调试，不编造模型实测成绩。
- 比率先聚合分子分母再除，零分母 null；查询记录与版本必须完整。

## Task 1 — 缺口回归与派生查询

- [x] 新建 `tests/member2_completion_test.py`，正式库 SQL 独立计算三个比率，验证分组、过滤、零分母及人均澄清；运行 `.venv/Scripts/python.exe tests/member2_completion_test.py`，先确认拒答或执行失败。
- [x] 新建 `agent/derived.py`，接口 `execute_ratio(workflow, slots, version, context) -> dict`；消费 `workflow._execute` 的基础指标响应，返回共享信封和双查询溯源。
- [x] 修改 `agent/workflow.py` 的拒答清单、歧义提示和派生路由；运行新增测试和 `tests/member2_workflow_test.py`。

## Task 2 — 时间、澄清与模型边界

- [x] 回归用例加入日期区间、非法日期、中文年月、相对日、排名、多轮澄清保持已有槽位、非对象模型响应；运行确认缺陷。
- [x] 新建 `agent/periods.py` 的 `parse_period(question) -> tuple`；修改 workflow 调用和澄清继承。同比/不支持两期比较明确拒答。
- [x] 加固 `agent/model.py` 的响应结构、workflow 的模型计划验证；新增 `agent/prompts/plan_v2.txt`，业务上下文含参考日期、表字段、单位和定义。
- [x] 运行新增测试、模型协议测试、原工作流测试，确认不吞掉用户明确条件。

## Task 3 — HTTP 运营 Agent 与交付

- [x] 新增真实 HTTP 测试，用测试服务调用 `/agent/query`，并验证连接失败状态和 CLI 退出码。
- [x] 新建 `agent/client.py` 的 `HTTPAgentClient.run(payload) -> dict`，修改 `scripts/run_operations_agent.py` 增加 `--api` 参数；加固 `agent/operations.py` 的无结果/截断限制。
- [x] 运行 `scripts/test_query_api.py`、`scripts/test_importer.py`、`scripts/validate_demo.py`、基础及新增 Agent 测试和成员三派生指标测试。
- [x] 更新 `docs/member2_delivery.md`、README，写实际验证证据和未实测限制；独立审查，修复发现的问题。
- [x] `git diff --check` 后提交功能分支并创建 PR；不自行合入 main。

交付：PR #1（https://github.com/rei320051-jpg/databridge/pull/1）；34项成员二测试及独立审查通过。
