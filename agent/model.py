"""Optional LLM plan adapters. Credentials never enter source control or logs.

支持两种后端（均只做"问题 → 结构化槽位"，校验与执行始终在本地）：
1. OpenAI 官方 Responses API（默认）：POST {base}/v1/responses
2. OpenAI 兼容 Chat Completions（DeepSeek 等）：设置环境变量
   DATABRIDGE_BASE_URL（如 https://api.deepseek.com）后自动走该通道，
   POST {base}/v1/chat/completions，response_format=json_object。

凭据只从环境变量或仓库根目录的 .env（已 gitignore）读取；
真实环境变量优先于 .env。密钥不写日志、不进异常信息。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from shared.contracts import DIMENSION_SPEC, METRIC_SPEC, REFERENCE_DATE

PROMPT_VERSION = "plan_v2"
PROMPT = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")


def _load_env_file() -> None:
    """零依赖加载仓库根目录 .env；只补缺省，不覆盖已存在的环境变量。"""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env_file()


class ModelFailure(Exception):
    pass


class ModelOutputInvalid(Exception):
    pass


class OpenAIPlanModel:
    """The model only proposes slots; validation and execution remain local."""

    def __init__(self, api_key=None, model=None, base_url=None, transport=None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model or os.environ.get("DATABRIDGE_MODEL")
        # 为空 → OpenAI 官方 Responses；非空 → OpenAI 兼容 Chat Completions（DeepSeek 等）
        self.base_url = (base_url if base_url is not None
                         else os.environ.get("DATABRIDGE_BASE_URL", "")).rstrip("/")
        self.transport = transport or urllib.request.urlopen
        # 纯观测字段：便于 S1/S2 真实模型复测统计调用次数与 token，不参与任何业务判断
        self.calls = 0
        self.last_usage = None
        self.last_model = None

    def _context(self, question: str) -> dict:
        return {
            "question": question,
            "reference_date": REFERENCE_DATE,
            "metrics": {k: {"label": v["label"], "synonyms": v["synonyms"],
                            "definition": v["definition"], "unit": v["unit"]}
                        for k, v in METRIC_SPEC.items()},
            "dimensions": DIMENSION_SPEC,
            "tables": {"orders": ["order_id", "customer_id", "region", "payment_status", "paid_at", "paid_amount_fen"],
                       "refunds": ["refund_id", "order_id", "refund_status", "refunded_at", "refund_amount_fen"],
                       "customers": ["customer_id", "customer_type"]},
            "relationships": ["refunds.order_id -> orders.order_id (many-to-one)",
                              "orders.customer_id -> customers.customer_id (many-to-one)"],
        }

    def _post(self, request, timeout: int):
        try:
            with self.transport(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # 不回显响应体，避免把鉴权信息带进异常/日志
            raise ModelFailure(f"模型服务返回 HTTP {exc.code}，请检查密钥、模型名与权限") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModelFailure("模型服务调用失败，请检查网络和模型配置") from exc

    def propose(self, question: str) -> dict:
        if not self.api_key or not self.model:
            raise ModelFailure("模型模式缺少 OPENAI_API_KEY 或 DATABRIDGE_MODEL 配置")
        self.calls += 1
        self.last_usage = None
        context = self._context(question)
        if self.base_url:
            return self._propose_chat_completions(context)
        return self._provise_responses(context)

    # -- DeepSeek 等 OpenAI 兼容 Chat Completions --------------------------
    def _propose_chat_completions(self, context: dict) -> dict:
        base = self.base_url
        url = (base if base.endswith("/v1") else base + "/v1") + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "stream": False,
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            method="POST",
        )
        body = self._post(request, timeout=30)
        self.last_usage = body.get("usage") if isinstance(body, dict) else None
        self.last_model = body.get("model") if isinstance(body, dict) else None
        try:
            text = body["choices"][0]["message"]["content"]
            result = json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ModelOutputInvalid("兼容模型未返回唯一的 JSON 文本") from exc
        if not isinstance(result, dict):
            raise ModelOutputInvalid("模型输出不是 JSON 对象")
        return result

    # -- OpenAI 官方 Responses API -----------------------------------------
    def _provise_responses(self, context: dict) -> dict:
        payload = {
            "model": self.model,
            "instructions": PROMPT,
            "input": json.dumps(context, ensure_ascii=False),
            "text": {"format": {"type": "json_object"}},
            "store": False,
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        body = self._post(request, timeout=15)
        self.last_usage = body.get("usage") if isinstance(body, dict) else None
        self.last_model = body.get("model") if isinstance(body, dict) else None
        try:
            if body.get("status") != "completed":
                raise ModelFailure("模型未完成结构化解析")
            output = body["output"]
            if not isinstance(output, list):
                raise ModelOutputInvalid("模型 output 必须是数组")
            chunks = []
            for item in output:
                if not isinstance(item, dict):
                    raise ModelOutputInvalid("模型 output 元素必须是对象")
                if item.get("type") != "message":
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    raise ModelOutputInvalid("模型 message.content 必须是数组")
                for part in content:
                    if not isinstance(part, dict):
                        raise ModelOutputInvalid("模型 content 元素必须是对象")
                    if part.get("type") == "refusal":
                        raise ModelOutputInvalid("模型拒绝解析，请改用规则模式")
                    if part.get("type") == "output_text":
                        if not isinstance(part.get("text"), str):
                            raise ModelOutputInvalid("模型文本类型错误")
                        chunks.append(part["text"])
            if len(chunks) != 1:
                raise ModelOutputInvalid("模型没有返回唯一的 JSON 文本")
            result = json.loads(chunks[0])
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ModelOutputInvalid("模型返回的 JSON 无效") from exc
        if not isinstance(result, dict):
            raise ModelOutputInvalid("模型输出不是 JSON 对象")
        return result
