# -*- coding: utf-8 -*-
"""契约参考服务：把页面侧参考实现暴露成 HTTP 接口。

## 为什么要有它

分工文档 §6.4 要求"变更后必须完成一次完整联调"，但三人正在同时开发三个模块，
互相之间没有可调用的对象，联调就无从谈起。本服务解决的是**联调的鸡生蛋问题**：
它用零第三方依赖的方式，把三分文档里的接口契约跑成一个真实可用的 HTTP 服务，
让三方从今天起就可以对着同一个东西开发。

## 三个端点（严格对齐 docs/接口契约补充_v1.1）

    GET  /health            {"status","dataset_version","tables"}
    POST /agent/query       {"question","context","clarification"} -> 结果信封
    POST /datasets/inspect  multipart/form-data CSV -> 质检报告

## 责任边界

**它不是正式后端。** 正式查询服务由成员 1 用 FastAPI 实现；本服务的价值在于
**定义行为**——成员 1 的实现跑同一批请求，应当得到逐字段一致的结果。
成员 2 可以直接对它开发 Agent，不必等成员 1。

之所以用标准库而不是 FastAPI：保证任何机器、任何 Python 环境都能直接跑，
不引入安装成本。请求体与响应体和 FastAPI 版本完全一致，替换实现不影响调用方。

## 运行

    python app/mock_server.py --port 8000

页面侧切换：

    $env:DATABRIDGE_BACKEND = "live"
    $env:DATABRIDGE_API = "http://127.0.0.1:8000"
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in (str(_ROOT), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mock_backend  # noqa: E402
import quality as quality_mod  # noqa: E402
from demo_data import demo_tables  # noqa: E402
from shared.contracts import API_ENDPOINTS, DATASET_VERSION, Status  # noqa: E402

_TABLES: dict = {}
_TABLES_LOCK = threading.Lock()


def ensure_tables() -> dict:
    """懒加载演示数据。生成一次后复用，避免每次请求重复构造。"""
    global _TABLES
    if not _TABLES:
        with _TABLES_LOCK:
            if not _TABLES:
                _TABLES = demo_tables()
    return _TABLES


# ---------------------------------------------------------------------------
# multipart 解析（Python 3.13 起 cgi 模块已移除，只能自己解析）
# ---------------------------------------------------------------------------

def parse_multipart(body: bytes, content_type: str) -> dict:
    """从 multipart/form-data 中提取文件，返回 {filename: text}。"""
    m = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type or "")
    if not m:
        raise ValueError("Content-Type 缺少 boundary")
    boundary = (m.group(1) or m.group(2)).strip().encode()

    files: dict = {}
    for part in body.split(b"--" + boundary):
        chunk = part.strip()
        if not chunk or chunk == b"--":
            continue
        head, sep, content = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        fname = re.search(r'filename="([^"]*)"', head.decode("utf-8", "replace"))
        if not fname:
            continue
        files[fname.group(1)] = content.rstrip(b"\r\n").decode("utf-8-sig", "replace")
    return files


# ---------------------------------------------------------------------------
# 业务处理
# ---------------------------------------------------------------------------

def handle_health() -> dict:
    tables = ensure_tables()
    return {
        "status": "ok",
        "dataset_version": DATASET_VERSION,
        "tables": sorted(tables),
        "rows": {k: int(len(v)) for k, v in tables.items()},
        "server": "数桥契约参考服务（非正式后端）",
        "contract": f"v{API_ENDPOINTS and '1.1'}",
    }


def handle_query(payload: dict) -> tuple:
    question = payload.get("question")
    if not question or not str(question).strip():
        return 400, {
            "status": Status.EXECUTION_FAILED,
            "message": "请求缺少 question 字段。",
            "query_id": "-",
            "dataset_version": DATASET_VERSION,
            "executed_at": datetime.now().isoformat(timespec="seconds"),
            "reason": "bad_request",
            "missing": ["question"],
            "suggestion": "请在请求体中提供 question。",
            "retryable": False,
        }

    resp = mock_backend.handle(
        question,
        context=payload.get("context") or None,
        clarification=payload.get("clarification"),
        tables=ensure_tables(),
    )
    return 200, resp


def handle_inspect(body: bytes, content_type: str) -> tuple:
    try:
        files = parse_multipart(body, content_type)
    except ValueError as exc:
        return 400, {"status": "error", "message": str(exc)}

    if not files:
        return 400, {"status": "error", "message": "未收到任何文件。"}

    tables = {}
    for fname, text in files.items():
        tname = quality_mod.infer_table_name(fname)
        try:
            tables[tname] = pd.read_csv(io.StringIO(text))
        except Exception as exc:  # noqa: BLE001
            return 400, {"status": "error", "message": f"读取 {fname} 失败：{exc}"}

    report = quality_mod.inspect_datasets(tables, version=DATASET_VERSION)
    return 200, report


# ---------------------------------------------------------------------------
# HTTP 层
# ---------------------------------------------------------------------------

class ContractHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DataBridgeContractReference/1.1"

    def log_message(self, fmt, *args):  # 静音默认日志，避免干扰调用方输出
        path = args[0] if args else ""
        code = args[1] if len(args) > 1 else ""
        sys.stderr.write(f"[{datetime.now():%H:%M:%S}] {code} {path}\n")

    # ---- helpers ----
    def _send(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    # ---- verbs ----
    def do_OPTIONS(self):  # noqa: N802
        self._send(200, {"status": "ok"})

    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] == "/health":
            self._send(200, handle_health())
        else:
            self._send(404, {
                "status": "error",
                "message": f"未支持的路径 {self.path}",
                "supported": ["/health", "/agent/query", "/datasets/inspect"],
            })

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        body = self._read_body()

        if path == "/agent/query":
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except json.JSONDecodeError as exc:
                self._send(400, {"status": "error", "message": f"请求体不是合法 JSON：{exc}"})
                return
            code, resp = handle_query(payload)
            self._send(code, resp)

        elif path == "/datasets/inspect":
            code, resp = handle_inspect(body, self.headers.get("Content-Type", ""))
            self._send(code, resp)

        else:
            self._send(404, {"status": "error", "message": f"未支持的路径 {path}"})


def main() -> None:
    ap = argparse.ArgumentParser(description="数桥 DataBridge 契约参考服务")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    ensure_tables()
    srv = ThreadingHTTPServer((args.host, args.port), ContractHandler)
    print(f"数桥契约参考服务已启动：http://{args.host}:{args.port}")
    print("端点：GET /health · POST /agent/query · POST /datasets/inspect")
    print("该服务用于联调，正式后端由成员 1 实现。Ctrl+C 停止。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
