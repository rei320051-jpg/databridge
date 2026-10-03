"""Example: python scripts/run_operations_agent.py 生成2026年9月经营简报"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.operations import monthly_brief
from agent.workflow import AgentWorkflow
from databridge.service import QueryService


def main():
    request = " ".join(sys.argv[1:]) or "生成2026年9月经营简报"
    database = os.environ.get("DATABRIDGE_DATABASE", str(ROOT / "outputs" / "demo-v1.1.sqlite3"))
    workflow = AgentWorkflow(QueryService(database=database))
    print(json.dumps(monthly_brief(workflow, request), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
