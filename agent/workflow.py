"""Validated natural-language gateway for the member-1 read-only query service."""

from __future__ import annotations

import calendar
import os
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from agent.periods import parse_period, UnsupportedPeriod
from agent.model import ModelFailure, ModelOutputInvalid, OpenAIPlanModel, PROMPT_VERSION
from shared.contracts import (
    ALLOWED_FILTER_KEYS, AMBIGUOUS_METRIC_TERMS, Comparison, DIMENSION_SPEC,
    Dimension, MAX_CLARIFICATION_ROUNDS, METRIC_SPEC, Metric, ReasonCode,
    REFERENCE_DATE, Sort, Status, clarification_field, clarification_id,
)

METRIC_TO_EXECUTOR = {
    Metric.PAID_ORDER_COUNT: "paid_orders",
    Metric.PAID_CUSTOMER_COUNT: "paying_customers",
    Metric.PAID_AMOUNT: "paid_amount",
    Metric.REFUND_AMOUNT: "successful_refund_amount",
    Metric.NET_SALES: "net_sales",
}
CUSTOMER_TYPES = {"新客户": "new", "老客户": "returning"}
REVERSE_CUSTOMER_TYPES = {v: k for k, v in CUSTOMER_TYPES.items()}
WRITE_WORDS = ("删除", "删掉", "清空", "修改", "更改", "更新", "改成", "改为", "插入", "写入", "drop", "delete", "update", "insert", "truncate")
RATES = ("转化率", "占比", "复购率", "同比", "退货率")
FUTURE = ("预测", "预估", "估算", "预计", "未来", "下个月会", "明年")
CAUSE = ("为什么", "原因", "导致", "归因", "什么因素")
CONFLICT = ("包含取消", "算上取消", "包含失败", "算上失败", "包含未支付", "不扣退款", "不计入退款")
GROUP_MARKERS = ("各", "每个", "按", "分别", "排名", "排行", "哪个", "哪些", "top", "前", "最高", "最低")
MOM_TERMS = ("环比", "对比上月", "跟上月比", "比上个月", "比上月", "下降最多", "降幅最大")


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    if not 1 <= month <= 12:
        raise ValueError("月份超出范围")
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def _previous_month(start: str, end: str) -> tuple[str, str]:
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    if (a.year, a.month) != (b.year, b.month) or a.day != 1 or b.day != calendar.monthrange(b.year, b.month)[1]:
        raise ValueError("环比仅支持完整自然月")
    left = a.replace(day=1) - timedelta(days=1)
    right = b.replace(day=1) - timedelta(days=1)
    return _month_bounds(left.year, left.month)[0], _month_bounds(right.year, right.month)[1]


def _envelope(status: str, message: str, version: str, **extra) -> dict:
    return {"status": status, "message": message, "query_id": str(uuid4()),
            "dataset_version": version, "executed_at": datetime.now(timezone.utc).isoformat(), **extra}


def _failure(status, message, version, reason, missing, suggestion, retryable=False, **extra):
    return _envelope(status, message, version, reason=reason, missing=missing,
                     suggestion=suggestion, retryable=retryable, **extra)


def _metric(question: str):
    # Longest explicit synonym wins. Ambiguous terms are checked only when no
    # unambiguous metric phrase was present ("净销售额" contains "销售额").
    matches = [(match.start(), match.end(), code) for code, spec in METRIC_SPEC.items()
               for term in spec['synonyms'] for match in re.finditer(re.escape(term.lower()), question.lower())]
    # Ignore only fully contained occurrences, e.g. 支付金额 inside 人均支付金额.
    # Separate mentions of total and per-customer spending still need clarification.
    matches = [(start, end, code) for start, end, code in matches if not any(
        a <= start and end <= b and b - a > end - start for a, b, _ in matches)]
    if matches:
        distinct = sorted({code for _, _, code in matches})
        if len(distinct) > 1:
            return None, distinct
        return distinct[0], None
    for term in sorted(AMBIGUOUS_METRIC_TERMS, key=len, reverse=True):
        if term in question:
            return None, AMBIGUOUS_METRIC_TERMS[term]
    return None, None


def _period(question: str):
    return parse_period(question)


def _slots(question: str, proposal: dict) -> dict:
    metric, ambiguous = _metric(question)
    criterion_ambiguous = any(term in question for term in ("最好", "最差", "哪个地区好", "表现最"))
    if metric is None and ambiguous is None and not criterion_ambiguous and proposal.get("metric") in Metric.ALL:
        metric = proposal["metric"]
    start, end = _period(question)
    vague_recent = any(term in question for term in ("最近", "近期", "近来", "这段时间")) and not re.search(r"(?:近|最近|过去)\d+天", question)
    has_time_cue = any(term in question for term in ("年", "月", "季度", "天", "昨天", "前天"))
    if not start and not end and not vague_recent and has_time_cue:
        start, end = proposal.get("date_start"), proposal.get("date_end")
    filters = {}
    for dimension, spec in DIMENSION_SPEC.items():
        hits = [value for value in spec["values"] if value in question]
        if hits:
            filters[dimension] = hits
    group = []
    for dimension, spec in DIMENSION_SPEC.items():
        if any(term in question for term in spec["synonyms"]) and any(mark in question for mark in GROUP_MARKERS):
            group.append(dimension)
        if len(filters.get(dimension, [])) > 1 and dimension not in group:
            group.append(dimension)
    if "哪个地区" in question and Dimension.REGION not in group:
        group.append(Dimension.REGION)
    # Never let a model silently add an unrequested group or filter. The
    # explicit user text and shared dimension dictionary are authoritative.
    comparison = Comparison.MOM if any(term in question for term in MOM_TERMS) else Comparison.NONE
    sort = Sort.ASC if any(term in question for term in ("最低", "最少", "最小", "最差")) else Sort.DESC
    return {"metric": metric, "ambiguous": ambiguous, "date_start": start, "date_end": end,
            "group_by": group, "filters": filters, "sort": sort, "comparison": comparison}


def _validate_slots(slots: dict) -> bool:
    try:
        if slots["metric"] is not None and slots["metric"] not in Metric.ALL:
            return False
        if not isinstance(slots["group_by"], list) or len(slots["group_by"]) > 2 or len(set(slots["group_by"])) != len(slots["group_by"]):
            return False
        if any(dim not in Dimension.ALL for dim in slots["group_by"]):
            return False
        if not isinstance(slots["filters"], dict) or any(k not in ALLOWED_FILTER_KEYS for k in slots["filters"]):
            return False
        for dim, values in slots["filters"].items():
            if isinstance(values, str):
                values = [values]
                slots["filters"][dim] = values
            if not isinstance(values, list) or not values or any(v not in DIMENSION_SPEC[dim]["values"] for v in values):
                return False
        if slots["sort"] not in Sort.ALL or slots["comparison"] not in Comparison.ALL:
            return False
        if 'ranking_limit' in slots and (type(slots['ranking_limit']) is not int or not 1 <= slots['ranking_limit'] <= 100):
            return False
        if 'rank_decline' in slots and type(slots['rank_decline']) is not bool:
            return False
        if (slots['date_start'] is None) != (slots['date_end'] is None):
            return False
        if slots["date_start"] is not None and slots["date_end"] is not None:
            start, end = date.fromisoformat(slots["date_start"]), date.fromisoformat(slots["date_end"])
            if start > end:
                return False
        return True
    except (TypeError, ValueError, KeyError):
        return False


def _clarify(target, reason, ask, choices, context, version):
    rounds = context.get("clarification_round", 0)
    if rounds >= MAX_CLARIFICATION_ROUNDS:
        return _failure(Status.INSUFFICIENT_DATA, "两轮澄清后仍缺少必要信息。", version,
                        "clarification_exhausted", [target], "请重新提问，并直接写明指标和月份。")
    options = [{"value": choice, "label": METRIC_SPEC[choice]["label"],
                "definition": METRIC_SPEC[choice]["definition"]} for choice in choices] if target == "metric" else [
                    {"value": choice, "label": choice, "definition": "自然月"} for choice in choices]
    return _envelope(Status.NEED_CLARIFICATION, ask, version, clarification={
        "id": clarification_id(target), "target_field": target, "reason_code": reason,
        "question": ask, "options": options, "allow_free_text": True,
        "resolved_context": context, "round": rounds + 1}, context=context)


def _money(value):
    return float((Decimal(int(value)) / Decimal(100)).quantize(Decimal("0.01")))


class AgentWorkflow:
    def __init__(self, service, model=None, mode=None):
        self.service = service
        self.mode = mode or os.environ.get("DATABRIDGE_AGENT_MODE", "rules")
        self.model = model or OpenAIPlanModel()

    def run(self, payload: dict) -> dict:
        version = self._version()
        if not isinstance(payload, dict) or not isinstance(payload.get("question"), str) or not payload["question"].strip():
            return _failure(Status.INSUFFICIENT_DATA, "请提供具体问题。", version,
                            "empty_question", ["question"], "请输入指标和时间范围。")
        question = payload["question"].strip()
        if len(question) > 1000:
            return _failure(Status.OUT_OF_SCOPE, "问题过长。", version, "question_too_long", [], "请缩短至 1000 字以内。")
        low = question.lower()
        if any(word in low for word in WRITE_WORDS):
            return _failure(Status.OUT_OF_SCOPE, "只读服务不支持修改数据。", version, "write_operation_refused", ["写操作能力"], "请改为取数问题。")
        if any(word in question for word in CONFLICT):
            return _failure(Status.OUT_OF_SCOPE, "要求的口径与指标字典不符。", version, "metric_definition_conflict", ["对应指标定义"], "请按当前字典口径提问，或先由三人确认新口径。")
        if any(word in question for word in RATES):
            return _failure(Status.OUT_OF_SCOPE, "当前不支持该比率指标或同比。", version, "derived_metric_unsupported", ["派生指标定义"], "请查询业务字典中的八个指标或使用环比。")
        if '比率' in question and _metric(question)[0] not in Metric.RATIO:
            return _failure(Status.OUT_OF_SCOPE, "该比率没有业务定义。", version,
                            "derived_metric_unsupported", ["比率指标定义"], "请查询业务字典中的三个派生指标。")
        if '增长率' in question and not any(term in question for term in MOM_TERMS):
            return _failure(Status.OUT_OF_SCOPE, "增长率需要明确比较基期。", version,
                            "missing_comparison_basis", ["比较基期"], "请改为某月环比增长率。")
        if any(word in question for word in FUTURE):
            return _failure(Status.OUT_OF_SCOPE, "当前不提供预测。", version, "no_forecast_capability", ["未来数据和预测模型"], "请查询已发生月份。")
        if any(word in question for word in CAUSE):
            return _failure(Status.INSUFFICIENT_DATA, "订单数据不能证明变化原因。", version,
                            "causal_reasoning_unsupported", ["营销活动数据", "价格调整记录", "外部环境数据"],
                            "可以查询变化幅度，但不能据此断言原因。")
        requested_version = payload.get("dataset_version")
        if requested_version and requested_version != version:
            return _failure(Status.INSUFFICIENT_DATA, "页面数据版本与正式后端不一致。", version,
                            "dataset_version_mismatch", [f"{requested_version} 对应的正式数据集"],
                            "请切换至正式数据集，勿混用页面模拟数据的结果。")
        context = payload.get("context") or {}
        if not isinstance(context, dict) or type(context.get("clarification_round", 0)) is not int:
            return _failure(Status.MODEL_OUTPUT_INVALID, "澄清上下文格式错误。", version, "invalid_context", [], "请重新提问。")
        context = {k: v for k, v in context.items() if k in ("metric", "date_start", "date_end", "group_by", "filters", "sort", "comparison", "clarification_round", "ranking_limit", "rank_decline")}
        if context.get("clarification_round", 0) < 0 or context.get("clarification_round", 0) > MAX_CLARIFICATION_ROUNDS:
            return _failure(Status.MODEL_OUTPUT_INVALID, "澄清轮数非法。", version, "invalid_context", [], "请重新提问。")
        # The page also sends its last successful context on a new question.
        # Only a clarification reply may inherit slots from an earlier turn.
        clarification = payload.get("clarification")
        if not clarification:
            context = {}
        proposal = {}
        if self.mode == "model":
            try:
                proposal = self.model.propose(question)
            except ModelOutputInvalid:
                return _failure(Status.MODEL_OUTPUT_INVALID, "模型未返回合法查询计划。", version,
                                "model_output_invalid", ["合法 JSON 查询计划"], "请重试或改用规则模式。", True)
            except ModelFailure:
                return _failure(Status.EXECUTION_FAILED, "模型调用失败。", version,
                                "model_unavailable", ["可用模型服务"], "检查密钥、模型和网络，或改用规则模式。", True)
            allowed = {"metric", "date_start", "date_end", "group_by", "filters", "sort", "comparison"}
            if (not isinstance(proposal, dict) or set(proposal) != allowed or
                    proposal["metric"] not in (*Metric.ALL, None) or
                    proposal["sort"] not in Sort.ALL or
                    proposal["comparison"] not in Comparison.ALL or
                    not isinstance(proposal["group_by"], list) or
                    not isinstance(proposal["filters"], dict) or
                    not _validate_slots(proposal)):
                return _failure(Status.MODEL_OUTPUT_INVALID, "模型输出字段或枚举不符合契约。", version,
                                "model_output_invalid", ["合法查询计划"], "请重试或改用规则模式。", True)
        elif self.mode != "rules":
            return _failure(Status.EXECUTION_FAILED, "AI 模式配置错误。", version,
                            "invalid_agent_mode", ["rules 或 model"], "检查 DATABRIDGE_AGENT_MODE。")
        if re.search(r"\d{1,2}月\s*(?:与|和|跟|对比|比较).*?\d{1,2}月", question):
            return _failure(Status.OUT_OF_SCOPE, "目前比较契约仅支持完整自然月环比。", version,
                            "unsupported_comparison_period", ["受支持的比较方式"], "请分别查询两期，或改用某月环比。")
        try:
            slots = _slots(question, proposal)
        except UnsupportedPeriod:
            return _failure(Status.OUT_OF_SCOPE, "目前比较契约仅支持完整自然月环比。", version,
                            "unsupported_comparison_period", ["受支持的比较方式"], "请分别查询两期，或改用某月环比。")
        except (ValueError, OverflowError):
            return _failure(Status.INSUFFICIENT_DATA, "日期不存在或时间区间不合法。", version,
                            "invalid_date_range", ["有效时间范围"], "请检查月份、日期及起止顺序。")
        number = re.search(r"(?:前|top\s*)(\d+|[一二两三四五六七八九十]+)(?:名|个)?", low)
        if number:
            token = number[1]
            slots['ranking_limit'] = int(token) if token.isdigit() else {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}.get(token)
            if not slots['ranking_limit'] or not 1 <= slots['ranking_limit'] <= 100:
                return _failure(Status.OUT_OF_SCOPE, "排名数量须为 1 至 100。", version,
                                "invalid_ranking_limit", [], "请使用前五名等明确数量。")
        slots['rank_decline'] = any(term in question for term in ('下降最多', '降幅最大'))
        if clarification:
            for field in ("metric", "date_start", "date_end", "group_by", "filters", "sort", "comparison", "ranking_limit", "rank_decline"):
                if field in context:
                    slots[field] = context[field]
            if "metric" in context:
                slots["ambiguous"] = None
        if clarification:
            if not isinstance(clarification, dict):
                return _failure(Status.MODEL_OUTPUT_INVALID, "澄清提交格式错误。", version,
                                "invalid_clarification", [], "请重新提问。")
            target = clarification_field(clarification.get("id", ""))
            if target not in ("metric", "date_range") or target != clarification.get("target_field", target):
                return _failure(Status.MODEL_OUTPUT_INVALID, "澄清目标无效。", version,
                                "invalid_clarification", [], "请重新提问。")
            choice = clarification.get("free_text") or clarification.get("choice")
            context["clarification_round"] = context.get("clarification_round", 0) + 1
            if isinstance(choice, str):
                choice = choice.strip()
            if target == "metric" and choice in Metric.ALL:
                slots["metric"] = choice
                slots["ambiguous"] = None
            elif target == "metric" and isinstance(choice, str):
                normalized = next((code for code, spec in METRIC_SPEC.items()
                                   if choice == spec["label"] or choice in spec["synonyms"]), None)
                if normalized:
                    slots["metric"] = normalized
                    slots["ambiguous"] = None
                else:
                    return _clarify("metric", ReasonCode.AMBIGUOUS_METRIC,
                                    "未识别指标，请从业务字典选择。", list(Metric.ALL), context, version)
            elif target == "date_range" and isinstance(choice, str) and re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", choice):
                slots["date_start"], slots["date_end"] = _month_bounds(*map(int, choice.split("-")))
            elif target == "date_range" and isinstance(choice, str):
                try:
                    ds, de = _period(choice)
                    if ds and de and date.fromisoformat(ds).day == 1 and de == _month_bounds(*map(int, ds[:7].split("-")))[1]:
                        slots["date_start"], slots["date_end"] = ds, de
                    else:
                        raise ValueError("月份不明确")
                except ValueError:
                    return _clarify("date_range", ReasonCode.AMBIGUOUS_TIME_RANGE,
                                    "未识别月份，请选择明确的自然月。",
                                    ["2026-06", "2026-07", "2026-08", "2026-09"], context, version)
            else:
                return _failure(Status.MODEL_OUTPUT_INVALID, "澄清选项不在允许范围内。", version,
                                "invalid_clarification_choice", [], "请选择页面给出的选项，或重新提问。")
        if not _validate_slots(slots):
            return _failure(Status.MODEL_OUTPUT_INVALID, "解析结果不符合共享契约。", version,
                            "invalid_plan", ["合法的指标、日期或维度"], "请用明确的时间和业务字典指标重新提问。")
        context.update({k: slots[k] for k in ("group_by", "filters", "sort", "comparison", "rank_decline")})
        if 'ranking_limit' in slots:
            context['ranking_limit'] = slots['ranking_limit']
        for field in ('date_start', 'date_end'):
            if slots[field]:
                context[field] = slots[field]
        if slots["ambiguous"] and not slots["metric"]:
            labels = '、'.join(METRIC_SPEC[code]['label'] for code in slots['ambiguous'])
            return _clarify("metric", ReasonCode.AMBIGUOUS_METRIC, f"请确认指标口径：{labels}？",
                            slots["ambiguous"], context, version)
        if not slots["metric"]:
            ask = "请指定评价指标，例如净销售额。" if "最好" in question else "你想查询哪个指标？"
            return _clarify("metric", ReasonCode.AMBIGUOUS_CRITERION if "最好" in question else ReasonCode.MISSING_FIELD,
                            ask, list(Metric.ALL), context, version)
        context["metric"] = slots["metric"]
        if not slots["date_start"] or not slots["date_end"]:
            return _clarify("date_range", ReasonCode.AMBIGUOUS_TIME_RANGE if "最近" in question else ReasonCode.MISSING_FIELD,
                            "请确认查询月份。", ["2026-06", "2026-07", "2026-08", "2026-09"], context, version)
        context.update({"date_start": slots["date_start"], "date_end": slots["date_end"]})
        if slots['metric'] in Metric.RATIO:
            from agent.derived import execute_ratio
            result = execute_ratio(self, slots, version, context)
        else:
            result = self._execute(slots, version, context)
        if result['status'] == Status.SUCCESS:
            if slots.get('rank_decline'):
                result['data'].sort(key=lambda r: (r.get('growth_rate') is None, r.get('growth_rate') or 0))
                result['ranking_basis'] = 'growth_rate_asc'
            if slots.get('ranking_limit'):
                result['data'] = result['data'][:slots['ranking_limit']]
                result['row_count'] = len(result['data'])
                result['ranking_limit'] = slots['ranking_limit']
        return result

    def _version(self):
        from databridge.service import QueryError, connect_readonly
        try:
            with closing(connect_readonly(self.service.database)) as conn:
                row = conn.execute("SELECT dataset_version FROM dataset_metadata").fetchone()
                return row[0] if row else "unavailable"
        except (OSError, sqlite3.Error, QueryError):
            return "unavailable"

    def _execute(self, slots, version, context):
        if version == "unavailable":
            return _failure(Status.EXECUTION_FAILED, "正式数据集尚未导入。", version,
                            "database_unavailable", ["已导入的 SQLite 数据集"], "先运行成员一的导入程序。", True)
        metric = slots["metric"]
        mapped = {}
        for dimension, values in slots["filters"].items():
            if dimension == Dimension.CUSTOMER_TYPE:
                mapped[dimension] = [CUSTOMER_TYPES[v] for v in values]
            elif dimension == Dimension.REGION:
                # DS-001（D1）：正式库与共享契约统一为同一份五地区词表，直接取契约枚举
                supported = set(DIMENSION_SPEC[Dimension.REGION]["values"])
                if any(v not in supported for v in values):
                    return _failure(Status.INSUFFICIENT_DATA, "所选地区不在正式数据集中。", version,
                                    "unsupported_region", ["该地区的正式数据"],
                                    "当前正式数据覆盖：" + "、".join(sorted(supported)) + "。")
                mapped[dimension] = values
        plan = {"metric": METRIC_TO_EXECUTOR[metric], "date_start": slots["date_start"],
                "date_end": slots["date_end"], "dataset_version": version,
                "group_by": slots["group_by"], "filters": mapped,
                "sort": slots["sort"], "limit": 100}
        if slots["comparison"] == Comparison.MOM:
            try:
                ds, de = _previous_month(slots["date_start"], slots["date_end"])
            except ValueError:
                return _failure(Status.OUT_OF_SCOPE, "环比仅支持完整自然月。", version,
                                "unsupported_comparison_period", ["完整自然月"], "请改用某月环比。")
            plan["compare"] = {"date_start": ds, "date_end": de}
        try:
            result, _ = self.service.run(plan)
        except Exception:
            return _failure(Status.EXECUTION_FAILED, "查询服务发生异常。", version,
                            "backend_exception", ["可用查询服务"], "请检查服务日志后重试。", True)
        if result["status"] != Status.SUCCESS:
            err = result.get("error", {})
            status = Status.INSUFFICIENT_DATA if result["status"] in ("insufficient_data", "dataset_not_found") else Status.EXECUTION_FAILED
            return _failure(status, err.get("message", "查询失败。"), version, err.get("code", "backend_error"),
                            ["完整可靠的数据"] if status == Status.INSUFFICIENT_DATA else [],
                            "检查数据范围或查询服务。", status == Status.EXECUTION_FAILED,
                            query_record_id=result.get("query_id"))
        try:
            trace = self.service.read_record(result["query_id"])["sql"]
        except Exception:
            return _failure(Status.EXECUTION_FAILED, "查询记录无法读取，结果不予返回。", version,
                            "trace_unavailable", ["可追溯查询记录"], "请检查查询记录目录。", True)
        rows = []
        for row in result["data"]:
            converted = dict(row)
            converted[metric] = converted.pop(plan["metric"])
            if METRIC_SPEC[metric]["unit"] == "元":
                for key in (metric, "compare_value", "difference"):
                    if converted.get(key) is not None:
                        converted[key] = _money(converted[key])
            if "customer_type" in converted:
                converted["customer_type"] = REVERSE_CUSTOMER_TYPES.get(converted["customer_type"], converted["customer_type"])
            rows.append(converted)
        warnings = [{"level": "warning", "code": w["code"], "message": w["message"],
                     "impact": "请结合数据质量说明解释结果。"} for w in result["warnings"]]
        extra_regions = sorted({row["region"] for row in rows if "region" in row}
                               - set(DIMENSION_SPEC[Dimension.REGION]["values"]))
        if extra_regions:
            warnings.append({"level": "warning", "code": "contract_region_mismatch",
                             "message": f"正式数据含共享维度枚举之外的地区：{'、'.join(extra_regions)}。",
                             "impact": "已如实展示数据库结果；三人仍需统一维度枚举。"})
        if slots["comparison"] == Comparison.MOM:
            warnings.append({"level": "info", "code": "comparison_period", "message":
                             f"环比基期为 {plan['compare']['date_start']} 至 {plan['compare']['date_end']}。",
                             "impact": "增长率在基期不大于零时为空。"})
        columns = list(rows[0]) if rows else list(slots["group_by"]) + [metric]
        return {"status": Status.SUCCESS,
                "message": f"已按「{METRIC_SPEC[metric]['label']}」口径查询；数据来自正式模拟数据集。",
                "query_id": result["query_id"], "dataset_version": version,
                "executed_at": datetime.now(timezone.utc).isoformat(), "data": rows,
                "columns": columns, "definition": METRIC_SPEC[metric]["definition"],
                "unit": METRIC_SPEC[metric]["unit"], "metric": metric,
                "applied_filters": slots["filters"], "date_start": slots["date_start"],
                "date_end": slots["date_end"], "group_by": slots["group_by"],
                "source_tables": result["source_tables"],
                "generated_sql": "\n".join(item["template"] for item in trace),
                "sql_parameters": [item["parameters"] for item in trace],
                "warnings": warnings, "row_count": len(rows), "truncated": result["truncated"],
                "plan": {k: slots[k] for k in ("metric", "date_start", "date_end", "group_by", "filters", "sort", "comparison")},
                "context": context, "prompt_version": PROMPT_VERSION if self.mode == "model" else None,
                "interpretation_mode": self.mode}
