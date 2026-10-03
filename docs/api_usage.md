# 查询接口怎么使用

这是成员 1 提供给其他模块调用的本地**结构化查询执行服务**。当前已有数据和接口；成员 2 需要把用户问题转换为查询请求，成员 3 需要把结果放到页面上。这里的 HTTP 验证使用手写请求，没有实现自然语言理解或完整产品页面。与共享仓库当前页面的差异见 `member1_integration_status.md`。

## 当前电脑直接启动

在PowerShell中执行：

```powershell
.\.venv\Scripts\python.exe scripts/verify_small.py --build-db  # 首次检出时先执行一次
.\.venv\Scripts\python.exe -m uvicorn databridge.api:app --host 127.0.0.1 --port 8001
```

保持该终端运行，在浏览器打开 http://127.0.0.1:8001/docs 。展开 POST /v1/query，点击 Try it out，粘贴以下请求，然后点击 Execute。不要将成员 3 页面的 live 模式直接指向此地址；它当前需要的是自然语言入口 `/agent/query`。

```json
{
  "metric": "net_sales",
  "date_start": "2026-09-01",
  "date_end": "2026-09-30",
  "group_by": ["region"],
  "filters": {},
  "sort": "desc",
  "limit": 100,
  "dataset_version": "small-v0.1"
}
```

结果应包含华东28000、华南18000、华北8000、西部5000，单位是分。页面应除以响应中的display_divisor=100，再显示元。不要把28000直接显示成28000元。

演示完回到启动终端按Ctrl+C即可停止。服务默认只监听本机，尚未提供其他电脑接入、账号权限或公网部署方案。

## 新电脑安装

需要Python 3.12。复制完整项目，在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe scripts/verify_small.py --build-db
```

如果outputs/small-v0.1.sqlite3已经存在，构建命令会拒绝覆盖；可使用不带--build-db的命令核对现有源样例。依赖文件锁定本次实测版本；尚未完成另一台电脑的实际部署验证。

## 自动验收

```powershell
.\.venv\Scripts\python.exe scripts/test_query_api.py
.\.venv\Scripts\python.exe scripts/smoke_http.py
```

第一条执行17项回归测试，包含10个手工场景的50个指标值和时间段比较。测试使用临时副本，结束后核对原数据库未变。第二条自动启动临时服务、通过真实HTTP请求验证、生成outputs/api_smoke.json并停止服务。

## 给成员2和成员3的交接要点

- POST /v1/query：接收结构化计划，返回数值、口径、单位、版本、警告和query_id。
- GET /v1/query-records/{query_id}：查看该次查询的SQL模板、参数、请求、返回结果及耗时。
- GET /health：检查进程响应及默认数据库文件是否存在；文件存在不代表完成数据质量验收。
- 支持5个指标、时间区间、地区/客户类型筛选与分组、排序及最多1000行返回。
- group_by=[]得到全局汇总；支付人数全局去重，不能把各地区人数直接相加。
- 失败响应data=null，应向用户展示error.message；不能显示为0元。
- compare可传入明确的date_start和date_end；返回当前值、compare_value、difference和growth_rate。对比值为0或负数时growth_rate为null并返回解释性警告。

默认使用outputs/small-v0.1.sqlite3。运行演示库前，可在当前PowerShell设置：

```powershell
$env:DATABRIDGE_DATABASE = (Resolve-Path outputs/demo-v1.0.sqlite3).Path
$env:DATABRIDGE_RECORDS = (Join-Path (Get-Location) 'outputs/demo-query-records')
```

随后使用同一条uvicorn启动命令。环境变量仅影响当前终端会话。

请求的可选参数会自动补齐；非法日期、未知字段、未知指标、空筛选数组、重复分组维度和非法limit会被拒绝。

## 已落实的查询约束

使用只读数据库连接、允许读取的表名单和固定参数化SQL。订单金额与退款金额独立聚合，避免多次退款造成订单金额重复。两部分在同一数据快照下计算。数据库执行使用约2秒预算，每1000条虚拟机指令检查一次，超时返回timeout；这不是整个HTTP请求的严格2秒响应保证。

成功结果必须有查询记录；记录保存失败时返回明确失败。可解析的计划失败同样写入记录；无法解析的JSON请求在入口直接拒绝。查询记录包含SQL及数据条件，当前接口定位为本机开发服务。

尚未实现网页上传控件和真实AI/页面联调。后端已有通用CSV目录检查与导入、质量报告、2万订单演示数据和时间比较；数值验证范围仍限于模拟数据及定义好的回归场景。
