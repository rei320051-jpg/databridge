"""Example: python scripts/run_operations_agent.py 生成2026年9月经营简报"""

from __future__ import annotations

import json
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.operations import monthly_brief
from agent.client import HTTPAgentClient
from agent.workflow import AgentWorkflow
from databridge.service import QueryService
from shared.contracts import Status


def main():
    parser = argparse.ArgumentParser(description='调用可信取数平台生成经营简报')
    parser.add_argument('request', nargs='*')
    parser.add_argument('--api', help='HTTP 服务地址，例如 http://127.0.0.1:8001')
    args = parser.parse_args()
    request = " ".join(args.request) or "生成2026年9月经营简报"
    database = os.environ.get("DATABRIDGE_DATABASE", str(ROOT / "outputs" / "demo-v1.1.sqlite3"))
    try:
        workflow = HTTPAgentClient(args.api) if args.api else AgentWorkflow(QueryService(database=database))
        result = monthly_brief(workflow, request)
    except ValueError:
        result = {'status': Status.EXECUTION_FAILED, 'message': 'API 地址格式错误，请提供 HTTP(S) 服务地址。'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == Status.SUCCESS else 2


if __name__ == "__main__":
    raise SystemExit(main())
