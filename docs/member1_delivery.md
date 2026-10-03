# 成员1完整交付说明

原始验收日期：2026-09-29。成员 1 本地实现和验证完成；2026-10-02 已将源码及验证材料复制到共享仓库的独立功能分支。本文件记录原始本地验收，不代表三人真实联调、页面 live 模式或另一台电脑部署已通过；当前差异见 `member1_integration_status.md`。

## 已经交付什么

1. 数据结构：客户、订单、退款、数据版本和数据质量警告表；一个订单支持多次退款。
2. 三套数据：人工核对数据、2万订单演示数据、9类异常测试数据。
3. 指标字典：支付订单数、支付人数、实付金额、成功退款金额、净销售额。
4. CSV检查与导入：发现字段、类型、重复、缺失、金额、时间、外键、覆盖范围和超额退款问题；通过后原子建库。
5. 查询执行器：日期、地区/客户类型筛选与分组、排序、行数限制、时间段比较。
6. 查询接口：健康检查、统一查询、查询记录读取；返回口径、单位、来源表、版本和数据质量警告。
7. 安全与可追溯：只读数据库、允许表名单、参数化SQL、执行超时、最大返回1000行、每次成功查询保存SQL模板和参数。
8. 标准答案：小型数据有人工计算表；演示数据有独立生成时汇总及文件校验值。

## 验收结果

| 检查 | 结果 |
| --- | --- |
| 小型数据 | 10场景×5指标三方一致；5项数据库约束和覆盖越界检查通过 |
| CSV导入 | 7项测试通过；8类错误阻止建库，大额警告可查询追溯 |
| 查询接口 | 17项测试通过；包含比较、只读、超时、错误状态和人数去重 |
| 演示数据 | 2,000客户、20,000订单、3,492退款，质量检查0错误0警告 |
| 演示答案 | 65个独立预期值全部一致 |
| 实际HTTP | 小型库和演示库均完成启动、查询、比较、追溯及停止验证 |
| 本机性能 | 最终100次代表性顺序查询：中位15.906ms，P95 47.417ms，最大50.417ms |

性能数字来自当前电脑，包含查询记录写入；测试由5种查询形态组成，不是并发或网络压测，提交材料中应保留这一限制。

## 关键文件

- schema.sql：数据库结构。
- config/metrics.json：指标定义。
- config/data_quality.json：质量规则。
- databridge/importer.py：检查与导入。
- databridge/service.py：只读查询执行。
- databridge/api.py：HTTP接口。
- data/small、data/demo、data/anomalies：三套数据。
- scripts/verify_small.py、test_importer.py、test_query_api.py、validate_demo.py：验证程序。
- docs/api_usage.md、data_import.md、query_contract.md：交接文档。

## 如何运行全部验收

在共享仓库根目录执行。首次检出时先按 `api_usage.md` 安装根目录依赖、构建小型与演示数据库；下面的命令不应依赖原电脑的绝对路径：

```powershell
.\.venv\Scripts\python.exe scripts/verify_small.py --build-db  # 首次构建；已存在时改为不带此参数
.\.venv\Scripts\python.exe scripts/import_dataset.py data/demo --database outputs/demo-v1.1.sqlite3  # 首次构建
.\.venv\Scripts\python.exe scripts/test_importer.py
.\.venv\Scripts\python.exe scripts/test_query_api.py
.\.venv\Scripts\python.exe scripts/validate_demo.py
.\.venv\Scripts\python.exe scripts/smoke_http.py
.\.venv\Scripts\python.exe scripts/smoke_demo_http.py
```

原始本地验收的六组检查全部通过；上方另列了首次检出必需的数据库构建步骤。详细实际结果可在被 `.gitignore` 排除的 `outputs/` 下重新生成；数据库和运行证据可由 CSV 及脚本重建。

## 团队下一步

- 成员 2 按 `query_contract.md` 生成结构化请求并调用 `POST /v1/query`；对外指标编码和状态需按 `member1_integration_status.md` 显式对齐。
- 成员 3 按 `display_divisor` 将后端整数分显示为元，展示 warnings、definition、dataset_version 和 query_id；不得混用页面模拟数据的版本与金额。
- 三人确认接口字段后做一次真实联调，再冻结协议。
- 另一台电脑按api_usage.md重建环境并运行六组验收。

截至原始验收日期，上述外部协作尚未开展；目前已开始共享仓库交付，但三方契约确认和真实联调仍未完成。

## 已知边界

- 客户类型是数据集固定标签，不等同于“查询期内首次购买者”。
- 地区采用下单时订单快照；退款继承原订单地区。
- 时间比较接收成员2解析后的明确日期，不负责理解“上个月”“同比”等自然语言。
- 服务定位为本机开发/演示接口，尚未增加登录、多人权限、TLS或公网部署。
- SQLite足以支持首版演示；若未来并发或数据量显著提高，再评估PostgreSQL等方案。
