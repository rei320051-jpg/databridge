# -*- coding: utf-8 -*-
"""数桥 DataBridge —— 三方共享接口契约（Source of Truth）

本模块是成员 1 / 成员 2 / 成员 3 唯一的契约来源，三个模块必须 import 本文件，
禁止在各自代码里另写字面量。

任何字段名或枚举取值的增删改，必须三人同意后修改本文件，
并同步更新 `docs/接口契约补充_v1.1_澄清与异常结构.md`。
修改记录写入 CHANGELOG。

对应文档：
  - 三人分工文档 §6.2 查询计划格式
  - 三人分工文档 §6.3 查询结果格式
  - 三人分工文档 §4.2.5 异常和不可回答问题的六种状态
  - 本文件 v1.1 新增：澄清协议、异常结构、HTTP 接口清单
"""

from __future__ import annotations

MODULE_VERSION = "1.1"
CONTRACT_DATE = "2026-09-30"
FROZEN_AFTER = "2026-10-08"  # 功能冻结日，之后只修 bug 不改核心接口

CHANGELOG = [
    {
        "version": "1.1",
        "date": "2026-09-30",
        "author": "成员 3",
        "note": "补充 need_clarification / insufficient_data / out_of_scope / "
                "execution_failed / model_output_invalid 的返回结构；新增澄清二次提交协议；"
                "冻结 metric / status / dimension / region 枚举取值；定义 HTTP 接口清单。",
    },
    {
        "version": "1.0",
        "date": "2026-09-28",
        "author": "团队",
        "note": "分工文档 §6.2 / §6.3 初版查询计划与查询结果结构。",
    },
]


# ---------------------------------------------------------------------------
# 1. 业务基准参数
# ---------------------------------------------------------------------------

#: 业务基准日。所有相对时间表达（本月 / 上个月 / 近 30 天）以此为锚点。
#: 该值必须与实际数据集覆盖范围一致，属于接口字段，变更需三人同意。
REFERENCE_DATE = "2026-09-30"

#: 当前数据集覆盖的时间范围（闭区间，自然月对齐）
DATASET_COVERAGE = {
    "start": "2026-06-01",
    "end": "2026-09-30",
    "months": ["2026-06", "2026-07", "2026-08", "2026-09"],
}

#: 数据集版本号。任何数据重新生成都必须递增，并写入查询结果。
DATASET_VERSION = "mock-v1.0-demo"

#: 金额单位。首版统一为「元」，保留 2 位小数。禁止在指标之间混用单位。
CURRENCY_UNIT = "元"

#: ---------------------------------------------------------------------------
#: 【待三人确认的口径议题 - 编号 IS-001】净销售额的「同期」如何归属？
#: ---------------------------------------------------------------------------
#: 分工文档 §3.2.3 只写了「净销售额 = 所选期间实付金额 - 同期成功退款金额」，
#: 未说明退款按哪个时间字段归属期间。不同理解会得到不同数字：
#:   方案 A（两条独立聚合）：实付金额按 pay_time 归属所选期间；
#:                           退款金额按 refund_time 归属所选期间；两者分别求和后相减。
#:   方案 B（按订单归属）：退款金额归属于「原订单支付时间」所在的期间。
#: 页面侧参考实现（app/mock_backend.py）采用【方案 A】，理由有二：
#:   1. 与分工文档 §3.2.3 对「成功退款金额」的定义完全一致（按退款发生时间）；
#:   2. 两条聚合彼此独立，结构上不可能发生一对多重复累计，
#:      从根上满足 §3.4「多次退款不会导致订单金额重复累加」的验收标准。
#: 当查询需要按地区/客户类型分组时，退款侧必须先按 order_id 预聚合，
#: 再经 orders → customers 取维度，最后按维度聚合。禁止直接
#: orders ⨝ refunds 明细连接后再 SUM(orders.pay_amount)。
#: 本议题必须在 10 月 8 日功能冻结前由三人确认并写死，否则同一问题
#: 会出现两个都对但不同的数字。确认后请把结论写入本节并递增 MODULE_VERSION。
NET_SALES_TIME_ATTRIBUTION = "method_a_independent_period_aggregation"
REFUND_AMOUNT_TIME_ATTRIBUTION = "by_refund_time"
NET_SALES_NO_DIRECT_JOIN = True  # 禁止 orders ⨝ refunds 明细连接后聚合金额
OPEN_ISSUES = [
    {
        "id": "IS-001",
        "title": "净销售额中「同期成功退款金额」的时间归属",
        "status": "待三人确认",
        "current_decision": NET_SALES_TIME_ATTRIBUTION,
        "alternative": "method_b_by_order_pay_time",
        "deadline": "2026-10-08",
        "owner": "三人共同确认，成员 3 记录",
    },
]


# ---------------------------------------------------------------------------
# 2. 指标枚举（分工文档 §3.2.3，首版固定 5 个，不可自由扩展）
# ---------------------------------------------------------------------------

class Metric:
    PAID_ORDER_COUNT = "paid_order_count"
    PAID_CUSTOMER_COUNT = "paid_customer_count"
    PAID_AMOUNT = "paid_amount"
    REFUND_AMOUNT = "refund_amount"
    NET_SALES = "net_sales"

    ALL = (
        "paid_order_count",
        "paid_customer_count",
        "paid_amount",
        "refund_amount",
        "net_sales",
    )


#: 指标字典。页面、查询服务、示例 Agent 必须共用同一份口径。
METRIC_SPEC = {
    Metric.PAID_ORDER_COUNT: {
        "label": "支付订单数",
        "unit": "单",
        "definition": "所选期间成功支付的订单数，按订单编号去重",
        "formula": "COUNT(DISTINCT order_id) WHERE pay_status = 'success'",
        "synonyms": ["支付订单数", "订单数", "订单量", "成交单数", "单量",
                     "多少笔订单", "多少笔", "笔数", "多少单", "几单"],
        "source_tables": ["orders"],
        "ambiguous": False,
    },
    Metric.PAID_CUSTOMER_COUNT: {
        "label": "支付人数",
        "unit": "人",
        "definition": "所选期间成功支付的客户数，按客户编号去重",
        "formula": "COUNT(DISTINCT customer_id) WHERE pay_status = 'success'",
        "synonyms": ["支付人数", "付款人数", "下单人数", "客户数", "买家数", "人数",
                     "多少客户", "多少个人", "多少人", "多少买家", "多少个客户"],
        "source_tables": ["orders"],
        "ambiguous": False,
    },
    Metric.PAID_AMOUNT: {
        "label": "实付金额",
        "unit": CURRENCY_UNIT,
        "definition": "所选期间成功支付订单的实付金额之和，不做退款扣减",
        "formula": "SUM(pay_amount) WHERE pay_status = 'success'",
        "synonyms": ["实付金额", "实付", "支付金额", "成交金额", "成交额", "GMV", "交易额"],
        "source_tables": ["orders"],
        "ambiguous": False,
    },
    Metric.REFUND_AMOUNT: {
        "label": "成功退款金额",
        "unit": CURRENCY_UNIT,
        "definition": "所选期间成功完成的退款金额之和，按退款单号去重",
        "formula": "SUM(refund_amount) WHERE refund_status = 'success'",
        "synonyms": ["成功退款金额", "退款金额", "退款额", "退款总额",
                     "退了多少钱", "退了多少", "一共退了", "一共退了多少"],
        "source_tables": ["refunds"],
        "ambiguous": False,
    },
    Metric.NET_SALES: {
        "label": "净销售额",
        "unit": CURRENCY_UNIT,
        "definition": "所选期间实付金额减去同期成功退款金额",
        "formula": (
            "SUM(orders.pay_amount) - SUM(refunds.refund_amount)。"
            "必须先在 refunds 侧按 order_id 预聚合，再与 orders 左连接，"
            "否则一对多关联会导致实付金额重复累计"
        ),
        "synonyms": ["净销售额", "净销", "净收入", "净成交额", "实际销售额",
                     "扣退款后的销售额", "扣掉退款", "扣除退款"],
        "source_tables": ["orders", "refunds"],
        "ambiguous": False,
    },
}


#: 歧义词 -> 候选指标。命中时必须澄清，不得使用默认口径直接回答。
#: 对应分工文档 §4.2.4 的第一个例子。
AMBIGUOUS_METRIC_TERMS = {
    "销售额": [Metric.NET_SALES, Metric.PAID_AMOUNT],
    "营业额": [Metric.NET_SALES, Metric.PAID_AMOUNT],
    "营收": [Metric.NET_SALES, Metric.PAID_AMOUNT],
    "业绩": [Metric.NET_SALES, Metric.PAID_AMOUNT],
    "收入": [Metric.NET_SALES, Metric.PAID_AMOUNT],
    "流水": [Metric.NET_SALES, Metric.PAID_AMOUNT],
    "退款多不多": [Metric.REFUND_AMOUNT, Metric.PAID_ORDER_COUNT],
    "退款情况": [Metric.REFUND_AMOUNT, Metric.PAID_ORDER_COUNT],
}


# ---------------------------------------------------------------------------
# 3. 维度与筛选
# ---------------------------------------------------------------------------

class Dimension:
    REGION = "region"
    CUSTOMER_TYPE = "customer_type"

    ALL = ("region", "customer_type")


DIMENSION_SPEC = {
    Dimension.REGION: {
        "label": "地区",
        "column": "region",
        "synonyms": ["地区", "区域", "大区", "各省", "地区维度", "按地区"],
        "values": ["华东", "华南", "华北", "西南", "华中"],
    },
    Dimension.CUSTOMER_TYPE: {
        "label": "客户类型",
        "column": "customer_type",
        "synonyms": ["客户类型", "客户分层", "新老客户", "按客户类型", "客户种类"],
        "values": ["新客户", "老客户"],
    },
}


#: 允许出现在 filters 里的键。白名单机制，防止模型构造出任意过滤条件。
ALLOWED_FILTER_KEYS = ("region", "customer_type")

#: filters 的取值可以是标量，也可以是数组。
#: 数组表示「同一维度多个取值」，例如「华东和华南的净销售额分别是多少」
#: -> {"region": ["华东", "华南"]}，此时应当同时按该维度分组，**分别**给出数值，
#: 而不是求和成一个数，也不是只返回其中某一个地区。
FILTER_VALUE_CAN_BE_LIST = True

#: 排序方向
class Sort:
    DESC = "desc"
    ASC = "asc"

    ALL = ("desc", "asc")


#: 比较方式。none=不比较，mom=环比。
class Comparison:
    NONE = "none"
    MOM = "mom"

    ALL = ("none", "mom")


# ---------------------------------------------------------------------------
# 4. 状态枚举（分工文档 §4.2.5，六种，不可增删）
# ---------------------------------------------------------------------------

class Status:
    SUCCESS = "success"
    NEED_CLARIFICATION = "need_clarification"
    INSUFFICIENT_DATA = "insufficient_data"
    OUT_OF_SCOPE = "out_of_scope"
    EXECUTION_FAILED = "execution_failed"
    MODEL_OUTPUT_INVALID = "model_output_invalid"

    ALL = (
        "success",
        "need_clarification",
        "insufficient_data",
        "out_of_scope",
        "execution_failed",
        "model_output_invalid",
    )


#: 页面展示标签（成员 3 使用）
STATUS_LABEL = {
    Status.SUCCESS: "查询成功",
    Status.NEED_CLARIFICATION: "需要你补充信息",
    Status.INSUFFICIENT_DATA: "当前数据不足",
    Status.OUT_OF_SCOPE: "超出首版支持范围",
    Status.EXECUTION_FAILED: "查询执行失败",
    Status.MODEL_OUTPUT_INVALID: "模型输出格式错误",
}

#: 页面视觉严重度（成员 3 使用）：info / warning / error
STATUS_SEVERITY = {
    Status.SUCCESS: "info",
    Status.NEED_CLARIFICATION: "warning",
    Status.INSUFFICIENT_DATA: "warning",
    Status.OUT_OF_SCOPE: "warning",
    Status.EXECUTION_FAILED: "error",
    Status.MODEL_OUTPUT_INVALID: "error",
}


# ---------------------------------------------------------------------------
# 5. 澄清协议（v1.1 新增，原文档缺失）
# ---------------------------------------------------------------------------

class ReasonCode:
    AMBIGUOUS_METRIC = "ambiguous_metric"          # 指标口径不明确
    AMBIGUOUS_CRITERION = "ambiguous_criterion"    # 评价标准不明确（如「哪个地区最好」）
    AMBIGUOUS_TIME_RANGE = "ambiguous_time_range"  # 时间范围不明确（如「最近」）
    AMBIGUOUS_GROUP_BY = "ambiguous_group_by"      # 分组维度不明确
    AMBIGUOUS_FILTER = "ambiguous_filter"          # 筛选条件不明确
    MISSING_FIELD = "missing_field"                # 槽位缺失

    ALL = (
        "ambiguous_metric",
        "ambiguous_criterion",
        "ambiguous_time_range",
        "ambiguous_group_by",
        "ambiguous_filter",
        "missing_field",
    )


REASON_LABEL = {
    ReasonCode.AMBIGUOUS_METRIC: "指标口径不明确",
    ReasonCode.AMBIGUOUS_CRITERION: "评价标准不明确",
    ReasonCode.AMBIGUOUS_TIME_RANGE: "时间范围不明确",
    ReasonCode.AMBIGUOUS_GROUP_BY: "分组维度不明确",
    ReasonCode.AMBIGUOUS_FILTER: "筛选条件不明确",
    ReasonCode.MISSING_FIELD: "必要信息缺失",
}

#: 澄清 id 编码规则：clr_<target_context_key>_<序号>
#: 例：clr_metric_001。客户端只需回传 id 与 choice，服务端即可无状态恢复上下文。
CLARIFICATION_ID_PREFIX = "clr_"

#: 澄清目标槽位 -> 合法取值域
CLARIFICATION_TARGETS = {
    "metric": list(Metric.ALL),
    "date_range": ["2026-06", "2026-07", "2026-08", "2026-09"],
    "group_by": list(Dimension.ALL),
    "criterion": list(Metric.ALL),
}


def clarification_id(target_field: str, seq: int = 1) -> str:
    """按约定生成澄清 id。"""
    return f"{CLARIFICATION_ID_PREFIX}{target_field}_{seq:03d}"


def clarification_field(clr_id: str) -> str:
    """从澄清 id 反解目标槽位；格式非法时返回空串。"""
    parts = (clr_id or "").split("_")
    return parts[1] if len(parts) >= 3 and parts[0] == "clr" else ""


# ---------------------------------------------------------------------------
# 6. 查询计划字段（分工文档 §6.2，字段名已冻结）
# ---------------------------------------------------------------------------

PLAN_KEYS = (
    "metric",        # str，Metric 之一
    "date_start",    # str，YYYY-MM-DD
    "date_end",      # str，YYYY-MM-DD
    "group_by",      # list[str]，Dimension 之一或空列表
    "filters",       # dict，键必须在 ALLOWED_FILTER_KEYS 内
    "sort",          # str，Sort 之一
    "limit",         # int，最大返回行数
    "comparison",    # str，Comparison 之一
)

PLAN_TEMPLATE = {
    "metric": "net_sales",
    "date_start": "2026-09-01",
    "date_end": "2026-09-30",
    "group_by": ["region"],
    "filters": {},
    "sort": "desc",
    "limit": 100,
    "comparison": "none",
}


# ---------------------------------------------------------------------------
# 7. 查询结果字段（分工文档 §6.3 + v1.1 扩展）
# ---------------------------------------------------------------------------

#: 所有状态都必须返回的字段（信封层）
RESULT_ENVELOPE_KEYS = (
    "status",           # str，Status 之一
    "message",          # str，面向用户的一句话说明
    "query_id",         # str，本次查询唯一编号
    "dataset_version",  # str
    "executed_at",      # str，ISO8601
)

#: status == success 时额外必须返回的字段
RESULT_SUCCESS_KEYS = (
    "data",             # list[dict]，结果行
    "columns",          # list[str]，结果列顺序
    "definition",       # str，所用指标口径
    "unit",             # str
    "metric",           # str
    "applied_filters",  # dict
    "date_start",       # str
    "date_end",         # str
    "group_by",         # list[str]
    "source_tables",    # list[str]
    "generated_sql",    # str，可展示给用户，用于追溯
    "warnings",         # list[dict]，数据质量警告
    "row_count",        # int
    "truncated",        # bool，是否因 limit 被截断
)

#: status == need_clarification 时额外必须返回的字段
RESULT_CLARIFICATION_KEYS = (
    "clarification",    # dict，见下方结构
)

#: 其余状态（insufficient_data / out_of_scope / execution_failed /
#: model_output_invalid）额外必须返回的字段
RESULT_FAILURE_KEYS = (
    "reason",           # str，机器可读原因码
    "missing",          # list[str]，说明缺少什么（数据 / 字段 / 能力）
    "suggestion",       # str，给用户的下一步建议
    "retryable",        # bool，是否值得重试
)

#: clarification 子结构
CLARIFICATION_TEMPLATE = {
    "id": "clr_metric_001",              # str，必须符合 clarification_id 规则
    "target_field": "metric",            # str，CLARIFICATION_TARGETS 的键
    "reason_code": "ambiguous_metric",   # str，ReasonCode 之一
    "question": "你说的「销售额」是指哪一个指标？",
    "options": [                         # list，2~5 项；为空时表示只能自由文本
        {
            "value": "net_sales",
            "label": "净销售额",
            "definition": "实付金额减去同期成功退款金额",
        }
    ],
    "allow_free_text": True,
    "resolved_context": {},              # dict，已经解析出的槽位，回传时原样带回
    "round": 1,                          # int，第几轮澄清，用于防止无限追问
}

#: 单次提问最多澄清轮数。超过则必须降级为 insufficient_data，不得反复追问。
#: 对应分工文档 §4.4「明确问题不会被无意义地反复追问」。
MAX_CLARIFICATION_ROUNDS = 2


# ---------------------------------------------------------------------------
# 8. 警告级别
# ---------------------------------------------------------------------------

class WarningLevel:
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    ALL = ("error", "warning", "info")


# ---------------------------------------------------------------------------
# 9. HTTP 接口清单（v1.1 新增，供成员 1 / 成员 2 实现）
# ---------------------------------------------------------------------------

API_ENDPOINTS = {
    "health": {
        "method": "GET",
        "path": "/health",
        "owner": "成员 1",
        "response": {"status": "ok", "dataset_version": DATASET_VERSION, "tables": ["orders", "refunds", "customers"]},
    },
    "query": {
        "method": "POST",
        "path": "/agent/query",
        "owner": "成员 2（入口）+ 成员 1（执行）",
        "request": {
            "question": "2026年9月各地区的净销售额",
            "context": {},
            "clarification": {
                "id": "clr_metric_001",
                "choice": "net_sales",
                "free_text": None,
            },
        },
        "request_note": "clarification 为可选字段；为空表示首轮提问。"
                        "客户端必须把上一轮返回的 resolved_context 原样放回 context。",
        "response": "见结果信封结构，status 取 Status.ALL 之一",
    },
    "inspect": {
        "method": "POST",
        "path": "/datasets/inspect",
        "owner": "成员 1",
        "request": "multipart/form-data，字段名 files，可多份 CSV；"
                   "文件名需包含 order / refund / customer 之一以识别表",
        "response": "见 docs/接口契约补充_v1.1_澄清与异常结构.md 第 5 节",
    },
}


# ---------------------------------------------------------------------------
# 10. 页面快捷示例（成员 3 使用，同时充当接口自测用例）
#   每一项为 (分类, 问题, 预期状态)
# ---------------------------------------------------------------------------

PRESET_EXAMPLES = [
    ("明确可答", "2026年9月各地区的净销售额", Status.SUCCESS),
    ("明确可答", "上个月华东地区的净销售额是多少", Status.SUCCESS),
    ("同义问法", "9月华东的订单量是多少", Status.SUCCESS),
    ("需澄清·指标口径", "9月的销售额是多少", Status.NEED_CLARIFICATION),
    ("需澄清·评价标准", "哪个地区最好", Status.NEED_CLARIFICATION),
    ("需澄清·时间范围", "最近的订单情况怎么样", Status.NEED_CLARIFICATION),
    ("数据不足·因果", "为什么华东地区9月净销售额下降了", Status.INSUFFICIENT_DATA),
    ("超出范围·预测", "预测一下下个月的净销售额", Status.OUT_OF_SCOPE),
    ("超出范围·写操作", "把订单表里9月的记录删掉", Status.OUT_OF_SCOPE),
    ("超出范围·派生率", "华东地区的退款率是多少", Status.OUT_OF_SCOPE),
]


__all__ = [
    "MODULE_VERSION", "CONTRACT_DATE", "FROZEN_AFTER", "CHANGELOG",
    "REFERENCE_DATE", "DATASET_COVERAGE", "DATASET_VERSION", "CURRENCY_UNIT",
    "NET_SALES_TIME_ATTRIBUTION", "REFUND_AMOUNT_TIME_ATTRIBUTION",
    "NET_SALES_NO_DIRECT_JOIN", "OPEN_ISSUES",
    "Metric", "METRIC_SPEC", "AMBIGUOUS_METRIC_TERMS",
    "Dimension", "DIMENSION_SPEC", "ALLOWED_FILTER_KEYS", "FILTER_VALUE_CAN_BE_LIST",
    "Sort", "Comparison",
    "Status", "STATUS_LABEL", "STATUS_SEVERITY",
    "ReasonCode", "REASON_LABEL", "CLARIFICATION_ID_PREFIX",
    "CLARIFICATION_TARGETS", "clarification_id", "clarification_field",
    "PLAN_KEYS", "PLAN_TEMPLATE",
    "RESULT_ENVELOPE_KEYS", "RESULT_SUCCESS_KEYS", "RESULT_CLARIFICATION_KEYS",
    "RESULT_FAILURE_KEYS", "CLARIFICATION_TEMPLATE", "MAX_CLARIFICATION_ROUNDS",
    "WarningLevel", "API_ENDPOINTS", "PRESET_EXAMPLES",
]
