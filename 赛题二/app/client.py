# -*- coding: utf-8 -*-
"""后端适配层：页面唯一的数据出口。

页面代码只依赖 QueryClient，不直接碰 mock_backend 或 HTTP。
后端就绪后把 mode 从 "mock" 改为 "live" 即可，页面代码零改动。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.contracts import DATASET_VERSION, Status  # noqa: E402


class BackendError(RuntimeError):
    """网络层或协议层失败。页面必须显示明确错误，不得伪造结果。"""


class QueryClient:
    def __init__(self, mode: str = "mock", base_url: str = "http://127.0.0.1:8000",
                 timeout: int = 20):
        self.mode = mode
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout
        self._tables = None
        #: 当前数据集版本。由页面从 dataset_registry 写入，随每次结果返回，用于追溯。
        self.dataset_version: str | None = None
        #: 当前数据集覆盖月份（YYYY-MM）；None 时用 mock 参考实现的内置覆盖区间。
        self.coverage_months: list | None = None

    # -- 数据源 ------------------------------------------------------------
    def set_tables(self, tables: dict, coverage_months: list | None = None) -> None:
        """mock 模式下注入数据表（用户上传或内置演示数据）。"""
        self._tables = tables
        self.coverage_months = coverage_months

    def _mock_tables(self) -> dict:
        if self._tables is not None:
            return self._tables
        from demo_data import demo_tables
        self._tables = demo_tables()
        return self._tables

    # -- HTTP --------------------------------------------------------------
    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise BackendError(f"后端返回 HTTP {exc.code}：{detail}") from exc
        except urllib.error.URLError as exc:
            raise BackendError(f"无法连接后端 {url}：{exc.reason}") from exc
        except Exception as exc:  # noqa: BLE001
            raise BackendError(f"请求后端失败：{exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BackendError(f"后端返回的不是合法 JSON：{raw[:200]}") from exc
        if "status" not in data:
            raise BackendError(f"后端返回缺少 status 字段：{list(data)[:10]}")
        return data

    # -- 统一入口 ----------------------------------------------------------
    def submit(self, question: str, context: dict | None = None) -> dict:
        """首次提问。"""
        if self.mode == "mock":
            import mock_backend
            return mock_backend.handle(question, context=context,
                                       tables=self._mock_tables(),
                                       dataset_version=self.dataset_version,
                                       coverage_months=self.coverage_months)
        payload = {"question": question, "context": context or {}}
        if self.dataset_version:
            payload["dataset_version"] = self.dataset_version
        return self._post("/agent/query", payload)

    def resolve_clarification(self, clarification: dict, choice: str,
                              question: str, context: dict | None = None,
                              free_text: str | None = None) -> dict:
        """回答澄清问题后重新提交。原问题必须一起带上。"""
        ctx = dict(context or {})
        payload_clr = {
            "id": clarification.get("id"),
            "target_field": clarification.get("target_field"),
            "choice": choice,
            "free_text": free_text,
        }
        if self.mode == "mock":
            import mock_backend
            return mock_backend.handle(question, context=ctx,
                                       clarification=payload_clr,
                                       tables=self._mock_tables(),
                                       dataset_version=self.dataset_version,
                                       coverage_months=self.coverage_months)
        body = {"question": question, "context": ctx, "clarification": payload_clr}
        if self.dataset_version:
            body["dataset_version"] = self.dataset_version
        return self._post("/agent/query", body)

    def inspect_files(self, files: dict) -> dict:
        """把上传的 CSV 交给后端做数据质量检查。

        :param files: {filename: bytes}
        mock 模式下退回本地实现，保证页面在接口未就绪时依然可用。
        """
        if self.mode == "mock":
            import io

            import pandas as pd
            from quality import infer_table_name, inspect_datasets
            tables = {}
            for fname, raw in files.items():
                tables[infer_table_name(fname)] = pd.read_csv(
                    io.BytesIO(raw) if isinstance(raw, bytes) else io.StringIO(raw))
            return inspect_datasets(tables, version=DATASET_VERSION)

        boundary = "----DataBridgeBoundary7f3a91"
        body = bytearray()
        for fname, raw in files.items():
            if isinstance(raw, str):
                raw = raw.encode("utf-8")
            body += f"--{boundary}\r\n".encode()
            body += (f'Content-Disposition: form-data; name="files"; '
                     f'filename="{fname}"\r\n').encode()
            body += b"Content-Type: text/csv\r\n\r\n"
            body += raw + b"\r\n"
        body += f"--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            f"{self.base_url}/datasets/inspect", data=bytes(body), method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout * 3) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise BackendError(f"质检接口返回 HTTP {exc.code}："
                               f"{exc.read().decode('utf-8', 'replace')[:300]}") from exc
        except urllib.error.URLError as exc:
            raise BackendError(f"无法连接质检接口：{exc.reason}") from exc

    # -- 健康检查 ----------------------------------------------------------
    def health(self) -> dict:
        if self.mode == "mock":
            return {"status": "ok", "mode": "mock", "note": "本地模拟后端，非最终服务"}
        try:
            with urllib.request.urlopen(f"{self.base_url}/health", timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"status": "unreachable", "mode": "live", "error": str(exc)}


# ---------------------------------------------------------------------------
# 页面辅助：把响应渲染成一句话摘要
# ---------------------------------------------------------------------------

def summarize(resp: dict) -> str:
    st = resp.get("status")
    if st == Status.NEED_CLARIFICATION:
        return resp.get("clarification", {}).get("question", "需要补充信息。")
    if st == Status.SUCCESS:
        rows = resp.get("row_count", 0)
        return f"查询完成，返回 {rows} 行结果。"
    return resp.get("message", "查询未完成。")
