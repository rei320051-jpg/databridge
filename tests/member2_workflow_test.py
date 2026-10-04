"""Run with: python tests/member2_workflow_test.py"""

from __future__ import annotations

import json
import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.model import ModelFailure, ModelOutputInvalid, OpenAIPlanModel
from agent.operations import monthly_brief
from agent.workflow import AgentWorkflow
from databridge.api import create_app
from databridge.service import QueryService
from shared.contracts import Metric, Status


class FakeModel:
    def __init__(self, result):
        self.result = result

    def propose(self, question):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = ROOT / "outputs" / "demo-v1.1.sqlite3"
        if not cls.database.exists():
            raise RuntimeError("先运行 python scripts/import_dataset.py data/demo --database outputs/demo-v1.1.sqlite3")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = QueryService(database=self.database, records=Path(self.temp.name))
        self.agent = AgentWorkflow(self.service, mode="rules")

    def tearDown(self):
        self.temp.cleanup()

    def test_explicit_metric_matches_trusted_result_and_converts_fen(self):
        result = self.agent.run({"question": "2026年9月净销售额是多少"})
        self.assertEqual(result["status"], Status.SUCCESS)
        self.assertEqual(result["metric"], Metric.NET_SALES)
        expected = json.loads((ROOT / "data" / "demo" / "expected.json").read_text(encoding="utf-8"))
        self.assertEqual(result["data"][0][Metric.NET_SALES], expected["monthly"]["2026-09"]["net_sales"] / 100)
        self.assertEqual(result["unit"], "元")
        self.assertEqual(result["dataset_version"], "demo-v1.1")
        self.assertTrue(result["generated_sql"])
        self.assertTrue(result["sql_parameters"])

    def test_synonyms_and_clarification(self):
        first = self.agent.run({"question": "9月销售额是多少"})
        self.assertEqual(first["status"], Status.NEED_CLARIFICATION)
        self.assertEqual({o["value"] for o in first["clarification"]["options"]},
                         {Metric.NET_SALES, Metric.PAID_AMOUNT})
        second = self.agent.run({"question": "9月销售额是多少",
                                 "context": first["clarification"]["resolved_context"],
                                 "clarification": {"id": first["clarification"]["id"],
                                                   "target_field": "metric", "choice": Metric.NET_SALES}})
        self.assertEqual(second["status"], Status.SUCCESS)
        self.assertEqual(second["metric"], Metric.NET_SALES)
        synonym = self.agent.run({"question": "9月华东订单量是多少"})
        self.assertEqual(synonym["status"], Status.SUCCESS)
        self.assertEqual(synonym["metric"], Metric.PAID_ORDER_COUNT)

    def test_missing_time_two_round_cap(self):
        first = self.agent.run({"question": "净销售额是多少"})
        self.assertEqual(first["status"], Status.NEED_CLARIFICATION)
        self.assertEqual(first["clarification"]["target_field"], "date_range")
        exhausted = self.agent.run({"question": "销售额是多少",
                                    "context": {"clarification_round": 2},
                                    "clarification": {"id": "clr_metric_001", "choice": Metric.NET_SALES}})
        self.assertEqual(exhausted["status"], Status.INSUFFICIENT_DATA)

    def test_two_clarifications_and_new_question_does_not_inherit_slots(self):
        first = self.agent.run({"question": "销售额是多少"})
        second = self.agent.run({"question": "销售额是多少",
                                 "context": first["clarification"]["resolved_context"],
                                 "clarification": {"id": first["clarification"]["id"],
                                                   "target_field": "metric", "choice": Metric.NET_SALES}})
        self.assertEqual(second["status"], Status.NEED_CLARIFICATION)
        self.assertEqual(second["clarification"]["target_field"], "date_range")
        third = self.agent.run({"question": "销售额是多少",
                                "context": second["clarification"]["resolved_context"],
                                "clarification": {"id": second["clarification"]["id"],
                                                  "target_field": "date_range", "choice": "2026-09"}})
        self.assertEqual(third["status"], Status.SUCCESS)
        self.assertEqual(third["metric"], Metric.NET_SALES)
        fresh = self.agent.run({"question": "8月订单量是多少", "context": third["context"]})
        self.assertEqual(fresh["status"], Status.SUCCESS)
        self.assertEqual(fresh["metric"], Metric.PAID_ORDER_COUNT)
        self.assertEqual(fresh["date_start"], "2026-08-01")

    def test_free_text_clarification_and_multiple_metrics(self):
        first = self.agent.run({"question": "销售额是多少"})
        second = self.agent.run({"question": "销售额是多少",
                                 "context": first["clarification"]["resolved_context"],
                                 "clarification": {"id": first["clarification"]["id"],
                                                   "free_text": "净销售额"}})
        third = self.agent.run({"question": "销售额是多少",
                                "context": second["clarification"]["resolved_context"],
                                "clarification": {"id": second["clarification"]["id"],
                                                  "free_text": "2026年9月"}})
        self.assertEqual(third["status"], Status.SUCCESS)
        many = self.agent.run({"question": "9月实付金额和净销售额是多少"})
        self.assertEqual(many["status"], Status.NEED_CLARIFICATION)

    def test_rejection_and_data_mismatch(self):
        cases = [
            ("为什么9月华东净销售额下降", Status.INSUFFICIENT_DATA),
            ("预测10月净销售额", Status.OUT_OF_SCOPE),
            ("删除9月订单", Status.OUT_OF_SCOPE),
            ("9月退款率", Status.OUT_OF_SCOPE),
            ("9月净销售额不扣退款", Status.OUT_OF_SCOPE),
            ("2027年9月净销售额", Status.INSUFFICIENT_DATA),
        ]
        for question, expected in cases:
            with self.subTest(question=question):
                result = self.agent.run({"question": question})
                self.assertEqual(result["status"], expected)
                self.assertNotIn("data", result)
        # DS-001（D1）：地区词表统一后，西南为契约内地区，应正常返回而非拒答
        southwest = self.agent.run({"question": "2026年9月西南净销售额"})
        self.assertEqual(southwest["status"], Status.SUCCESS)
        self.assertTrue(southwest["data"])
        wrong = self.agent.run({"question": "2026年9月净销售额", "dataset_version": "ds-mock"})
        self.assertEqual(wrong["reason"], "dataset_version_mismatch")

    def test_mom_and_operations_agent(self):
        result = self.agent.run({"question": "2026年9月各地区净销售额环比"})
        self.assertEqual(result["status"], Status.SUCCESS)
        self.assertTrue(result["data"])
        self.assertIn("compare_value", result["data"][0])
        # DS-001（D1）：词表统一后不应再出现地区枚举不一致警告
        self.assertFalse(any(w["code"] == "contract_region_mismatch" for w in result["warnings"]))
        brief = monthly_brief(self.agent, "生成2026年9月经营简报")
        self.assertEqual(brief["status"], Status.SUCCESS)
        self.assertEqual(brief["dataset_version"], "demo-v1.1")
        self.assertIn("不能推断变化原因", brief["brief"])

    def test_model_failure_and_invalid(self):
        bad = AgentWorkflow(self.service, model=FakeModel(ModelOutputInvalid("bad")), mode="model")
        self.assertEqual(bad.run({"question": "9月净销售额"})["status"], Status.MODEL_OUTPUT_INVALID)
        failed = AgentWorkflow(self.service, model=FakeModel(ModelFailure("down")), mode="model")
        self.assertEqual(failed.run({"question": "9月净销售额"})["status"], Status.EXECUTION_FAILED)
        malformed = AgentWorkflow(self.service, model=FakeModel({"metric": "fake"}), mode="model")
        self.assertEqual(malformed.run({"question": "9月净销售额"})["status"], Status.MODEL_OUTPUT_INVALID)

    def test_model_adapter_uses_structured_json_and_backend_still_calculates(self):
        seen = {}

        def transport(request, timeout):
            seen["path"] = request.full_url
            seen["request"] = json.loads(request.data)
            proposal = {"metric": Metric.NET_SALES, "date_start": "2026-09-01",
                        "date_end": "2026-09-30", "group_by": [], "filters": {},
                        "sort": "desc", "comparison": "none"}
            reply = {"status": "completed", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": json.dumps(proposal)}]}]}
            return io.BytesIO(json.dumps(reply).encode("utf-8"))

        model = OpenAIPlanModel(api_key="test-only", model="test-model", transport=transport)
        result = AgentWorkflow(self.service, model=model, mode="model").run({"question": "9月净销售额"})
        self.assertEqual(result["status"], Status.SUCCESS)
        self.assertEqual(result["interpretation_mode"], "model")
        self.assertEqual(seen["request"]["text"]["format"]["type"], "json_object")
        self.assertEqual(seen["path"], "https://api.openai.com/v1/responses")
        vague = AgentWorkflow(self.service, model=model, mode="model").run({"question": "最近净销售额"})
        self.assertEqual(vague["status"], Status.NEED_CLARIFICATION)
        invented = {"metric": Metric.NET_SALES, "date_start": "2026-09-01",
                    "date_end": "2026-09-30", "group_by": ["region"],
                    "filters": {"region": ["华东"]}, "sort": "desc", "comparison": "none"}
        guarded = AgentWorkflow(self.service, model=FakeModel(invented), mode="model")
        aggregate = guarded.run({"question": "2026年9月净销售额"})
        self.assertEqual(aggregate["status"], Status.SUCCESS)
        self.assertEqual(aggregate["applied_filters"], {})
        self.assertEqual(aggregate["group_by"], [])
        criterion = guarded.run({"question": "哪个地区最好"})
        self.assertEqual(criterion["status"], Status.NEED_CLARIFICATION)

    def test_member3_development_question_statuses(self):
        # These cases assume the page's June-September mock dataset. The
        # formal backend covers January-September; since DS-001 (D1) it also
        # uses the contract five-region vocabulary, so D10 (Southwest) now
        # succeeds and only D24 (March, outside page coverage) differs.
        dataset_specific = {"D24": Status.SUCCESS}
        # v1.2 派生指标（口径冻结确认单 2026-10-04）：页面管线已支持退款率/客单价/
        # 支付人均消费，但成员 1 执行层尚未实现比率聚合，工作流在此之前继续拒答；
        # D27 未给时间，页面侧预期 need_clarification（时间澄清）。
        # 待成员 1/2 按确认单落地后删除本覆写。
        backend_pending = {"D27": Status.OUT_OF_SCOPE}
        for filename in ("测试题_开发集_30题.csv", "测试题_开发集_补充回归7题.csv"):
            with (ROOT / "tests" / filename).open(encoding="utf-8-sig", newline="") as handle:
                for case in csv.DictReader(handle):
                    with self.subTest(id=case["题号"], question=case["问题"]):
                        result = self.agent.run({"question": case["问题"]})
                        expected = (dataset_specific.get(case["题号"])
                                    or backend_pending.get(case["题号"]))
                        allowed = {expected} if expected else set(case["预期状态"].split("或"))
                        self.assertIn(result["status"], allowed)

    def test_http_entry(self):
        from fastapi.testclient import TestClient
        app = create_app(self.service)
        with TestClient(app) as client:
            response = client.post("/agent/query", json={"question": "2026年9月净销售额"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], Status.SUCCESS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
