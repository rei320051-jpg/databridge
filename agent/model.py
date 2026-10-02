"""Optional OpenAI Responses adapter. Credentials never enter source control or logs."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from shared.contracts import DIMENSION_SPEC, METRIC_SPEC

PROMPT_VERSION = "plan_v1"
PROMPT = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")


class ModelFailure(Exception):
    pass


class ModelOutputInvalid(Exception):
    pass


class OpenAIPlanModel:
    """The model only proposes slots; validation and execution remain local."""

    def __init__(self, api_key=None, model=None, transport=None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model or os.environ.get("DATABRIDGE_MODEL")
        self.transport = transport or urllib.request.urlopen

    def propose(self, question: str) -> dict:
        if not self.api_key or not self.model:
            raise ModelFailure("模型模式缺少 OPENAI_API_KEY 或 DATABRIDGE_MODEL 配置")
        context = {
            "question": question,
            "metrics": {k: {"label": v["label"], "synonyms": v["synonyms"]}
                        for k, v in METRIC_SPEC.items()},
            "dimensions": DIMENSION_SPEC,
        }
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
        try:
            with self.transport(request, timeout=15) as response:
                body = json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModelFailure("模型服务调用失败，请检查网络和模型配置") from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ModelOutputInvalid("模型服务返回的响应不是合法 JSON") from exc
        if body.get("status") != "completed":
            raise ModelFailure("模型未完成结构化解析")
        chunks = [content.get("text", "") for item in body.get("output", [])
                  if item.get("type") == "message"
                  for content in item.get("content", []) if content.get("type") == "output_text"]
        if len(chunks) != 1:
            raise ModelOutputInvalid("模型没有返回唯一的 JSON 文本")
        try:
            result = json.loads(chunks[0])
        except json.JSONDecodeError as exc:
            raise ModelOutputInvalid("模型返回的 JSON 无效") from exc
        if not isinstance(result, dict):
            raise ModelOutputInvalid("模型输出不是 JSON 对象")
        return result
