# 查询协议草案 v0.1.0

状态：待成员2、成员3确认，尚未冻结。2026-09-29已实现本地HTTP服务 POST /v1/query，支持5个指标、筛选分组和时间段比较。使用说明见api_usage.md。

> **更新（2026-10-06）**：本协议已在联调中实际落地并冻结。请求/响应的指标、状态、维度枚举以唯一事实来源
> `shared/contracts.py`（**v1.2**）为准；本文件作为 v0.1 历史草案保留，字段细节如与契约不一致以契约为准。
> 当前服务端点：`/health`、`/v1/query`（5 个基础指标）、`/agent/query`（自然语言入口，含 3 个派生比率的网关组合）、
> `/v1/query-records/{id}`。派生比率在 Agent 层组合两次分量查询实现，`/v1/query` 原生比率接口列为二期。

## 请求

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

机器可读结构位于 contracts/query_plan.schema.json。日期包括首尾两天，按北京时间执行。缺省字段由后端显式补齐，JSON Schema中的default本身不会自动写入。日期须开启格式校验，并额外检查开始不晚于结束、数据覆盖及版本存在性。必填项缺失由AI层澄清，后端返回 invalid_plan。

filters同一字段内为OR，不同字段间为AND；空对象表示无筛选，不接受空数组。退款继承原订单地区、客户类型；两类事件应用相同维度筛选，各自按支付/成功退款时间筛选。group_by=[]返回一行汇总；覆盖范围内无数据时汇总为0，分组结果为空数组。超出覆盖范围返回 insufficient_data，不返回伪装完整的局部总数。

sort按所选指标值排序，并以分组字段字符串升序稳定打破平局；先完成全量聚合再执行limit，发生截断时返回truncated=true及警告。禁止传入SQL、表名或任意表达式。

可选compare提供显式基期日期；由成员2解析“环比/同比”为两个区间。后端返回本期指标值、compare_value、difference及growth_rate=`(本期−基期)/基期`。基期为0或负值时增长率为null并给出警告。比较分组保留两期分组的并集，排序按本期值；若需要按下降幅度排名，示例Agent可取得完整结果后按difference处理。

## 成功响应示例

以下华东筛选示例对应请求中 filters={"region":["华东"]}；金额采用整数分。成员1已确认按分传递、按元显示，前端根据display_divisor显示280元；整个接口格式仍待成员2/3确认。

```json
{
  "status": "success",
  "query_id": "example-only",
  "metric": "net_sales",
  "data": [{"region": "华东", "net_sales": 28000}],
  "definition": "所选期间实付金额减去同期成功退款金额",
  "unit": "分",
  "display_unit": "元",
  "display_divisor": 100,
  "date_start": "2026-09-01",
  "date_end": "2026-09-30",
  "timezone": "Asia/Shanghai",
  "group_by": ["region"],
  "filters": {"region": ["华东"]},
  "source_tables": ["orders", "refunds"],
  "dataset_version": "small-v0.1",
  "dictionary_version": "0.1.0",
  "warnings": [{"code": "SIMULATED_DATA", "message": "当前数据集为虚构模拟数据"}],
  "truncated": false
}
```

计数指标unit为单/人，display_divisor为1；涉及客户类型时source_tables加入customers。真实query_id由后端生成，GET /v1/query-records/{query_id}可读取执行记录（SQL模板、绑定参数、版本、状态及耗时）；此处example-only仅为文档占位。

## 失败响应约定

```json
{
  "status": "insufficient_data",
  "data": null,
  "error": {"code": "OUTSIDE_COVERAGE", "message": "请求区间超出数据集覆盖范围"},
  "warnings": []
}
```

| 后端状态 | HTTP | 含义 |
| --- | --- | --- |
| success | 200 | 查询成功 |
| invalid_plan | 422 | 缺字段、格式或取值非法 |
| insufficient_data | 422 | 数据覆盖不足或质量错误阻止可靠计算 |
| unsupported | 422 | 请求合法但该阶段功能尚未实现 |
| dataset_not_found | 404 | 指定版本不存在 |
| execution_failed | 500 | 数据库执行失败 |
| timeout | 504 | 查询超时 |

失败不得返回虚构数值。warnings统一为包含code/message的对象数组。需要澄清、模型格式错误等状态由成员2的AI层处理，不冒充后端执行结果。

## 团队待确认清单

1. 5个指标ID和输入/输出字段是否采用本草案。
2. 金额API统一返回整数分，展示元；避免浮点金额。
3. 客户类型使用固定标签，地区采用订单快照。
4. 单数据库单版本，显式覆盖区间；末日包含。
5. 比较结构、负基期规则、筛选数组、错误状态是否满足成员2/3需要。

成员1已给出可讨论的具体方案；尚未联系其他成员或获得确认。变更后更新版本及样例，10月8日按原计划冻结。
