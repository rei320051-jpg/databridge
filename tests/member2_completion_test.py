"""Member-2 acceptance regressions; no holdout questions used."""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import subprocess
import os
import socket
import time
import unittest
from pathlib import Path
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.model import ModelOutputInvalid, OpenAIPlanModel
from agent.workflow import AgentWorkflow
from databridge.service import QueryService
from shared.contracts import METRIC_SPEC, Metric, Status


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = QueryService(ROOT / 'outputs/demo-v1.1.sqlite3', Path(self.temp.name))
        self.agent = AgentWorkflow(self.service, mode='rules')

    def tearDown(self):
        self.temp.cleanup()

    def query(self, text):
        return self.agent.run({'question': text})

    def test_three_ratios_match_independent_sql(self):
        with closing(sqlite3.connect(self.service.database)) as conn:
            amount, orders, customers = conn.execute(
                "SELECT SUM(paid_amount_fen), COUNT(DISTINCT order_id), COUNT(DISTINCT customer_id) "
                "FROM orders WHERE payment_status='paid' AND paid_at >= '2026-09-01' AND paid_at < '2026-10-01'"
            ).fetchone()
            refund = conn.execute("SELECT SUM(refund_amount_fen) FROM refunds WHERE refund_status='success' "
                                  "AND refunded_at >= '2026-09-01' AND refunded_at < '2026-10-01'").fetchone()[0]
        for label, metric, expected in [('退款率', Metric.REFUND_RATE, round(refund / amount * 100, 2)),
                                        ('客单价', Metric.AVG_ORDER_VALUE, round(amount / 100 / orders, 2)),
                                        ('支付人均消费', Metric.PAID_PER_CUSTOMER, round(amount / 100 / customers, 2))]:
            with self.subTest(metric=metric):
                result = self.query('2026年9月' + label)
                self.assertEqual(result['status'], Status.SUCCESS)
                self.assertEqual(result['data'][0][metric], expected)
                self.assertEqual(result['metric_kind'], 'ratio')
                self.assertEqual(len(result['component_query_ids']), 2)
                for query_id in result['component_query_ids']:
                    self.assertTrue(self.service.read_record(query_id)['sql'])

    def test_filtered_group_ratio_components(self):
        result = self.query('2026年9月新客户各地区退款率')
        self.assertEqual(result['status'], Status.SUCCESS)
        self.assertEqual(result['applied_filters'], {'customer_type': ['新客户']})
        self.assertEqual(result['group_by'], ['region'])
        for row in result['data']:
            self.assertAlmostEqual(row[Metric.REFUND_RATE], round(row['numerator_value'] / row['denominator_value'] * 100, 2))
        self.assertEqual(result['components']['denominator_metric'], Metric.PAID_AMOUNT)

    def test_zero_denominator_and_refund_only_group(self):
        self.agent = AgentWorkflow(QueryService(ROOT / 'outputs/small-v0.1.sqlite3', Path(self.temp.name)), mode='rules')
        result = self.query('2026年10月各地区退款率')
        self.assertEqual(result['status'], Status.SUCCESS)
        south = next(r for r in result['data'] if r['region'] == '华南')
        self.assertIsNone(south[Metric.REFUND_RATE])
        self.assertEqual(south['numerator_value'], 80)
        self.assertEqual(south['denominator_value'], 0)
        self.assertTrue(any(w['code'] == 'ZERO_DENOMINATOR' for w in result['warnings']))

    def test_ratio_mom_computes_rates_before_comparing(self):
        result = self.query('2026年9月各地区客单价环比')
        self.assertEqual(result['status'], Status.SUCCESS)
        for row in result['data']:
            self.assertAlmostEqual(row['difference'], round(row[Metric.AVG_ORDER_VALUE] - row['compare_value'], 2), places=2)
            self.assertAlmostEqual(row['growth_rate'], (row[Metric.AVG_ORDER_VALUE] - row['compare_value']) / row['compare_value'], places=4)

    def test_human_average_clarification_preserves_month(self):
        first = self.query('2026年9月人均消费')
        self.assertEqual(first['status'], Status.NEED_CLARIFICATION)
        self.assertEqual([o['value'] for o in first['clarification']['options']], [Metric.PAID_PER_CUSTOMER, Metric.AVG_ORDER_VALUE])
        self.assertIn('人均', first['clarification']['question'])
        reply = self.agent.run({'question': '支付人均消费', 'context': first['context'],
                               'clarification': {'id': first['clarification']['id'], 'choice': Metric.PAID_PER_CUSTOMER}})
        self.assertEqual(reply['status'], Status.SUCCESS)
        self.assertEqual(reply['date_start'], '2026-09-01')

    def test_date_ranges_never_silently_query_first_day(self):
        for question in ['2026-09-01至2026-09-30实付金额', '2026年9月1日到9月30日实付金额']:
            with self.subTest(question=question):
                result = self.query(question)
                self.assertEqual(result['status'], Status.SUCCESS)
                self.assertEqual((result['date_start'], result['date_end']), ('2026-09-01', '2026-09-30'))

    def test_invalid_dates_return_state_not_exception(self):
        for question in ['2026年13月实付金额', '2026年2月30日实付金额', '2026-09-30至2026-09-01实付金额']:
            with self.subTest(question=question):
                try:
                    result = self.query(question)
                except Exception as exc:
                    self.fail(f'Invalid user date escaped workflow: {exc}')
                self.assertNotEqual(result['status'], Status.SUCCESS)
                self.assertNotIn('data', result)

    def test_chinese_year_relative_day_and_quarter(self):
        cases = [('2025年九月净销售额', Status.INSUFFICIENT_DATA, None),
                 ('昨天订单数', Status.SUCCESS, '2026-09-29'),
                 ('第三季度净销售额', Status.SUCCESS, '2026-07-01')]
        for question, status, start in cases:
            with self.subTest(question=question):
                result = self.query(question)
                self.assertEqual(result['status'], status)
                if start:
                    self.assertEqual(result['date_start'], start)

    def test_clarification_retains_mom_and_sort(self):
        first = self.query('2026年9月各地区销售额环比最低')
        reply = self.agent.run({'question': '净销售额', 'context': first['context'],
                               'clarification': {'id': first['clarification']['id'], 'choice': Metric.NET_SALES}})
        self.assertEqual(reply['status'], Status.SUCCESS)
        self.assertEqual(reply['plan']['comparison'], 'mom')
        self.assertEqual(reply['plan']['sort'], 'asc')

    def test_ranking_returns_requested_count_and_decline_order(self):
        result = self.query('2026年9月净销售额最高的前两名地区')
        self.assertEqual(result['status'], Status.SUCCESS)
        self.assertEqual(len(result['data']), 2)
        result = self.query('2026年9月各地区净销售额下降最多')
        self.assertEqual(result['status'], Status.SUCCESS)
        values = [row['growth_rate'] for row in result['data'] if row['growth_rate'] is not None]
        self.assertEqual(values, sorted(values))

    def test_unsupported_two_period_comparison_is_explicit(self):
        for question in ['2026年9月与2026年7月净销售额比较', '9月净销售额与7月相比', '九月和七月净销售额', '9月、8月分别有多少订单', '9月1日与9月30日实付金额比较', '2026年9月1日与9月30日实付金额比较']:
            with self.subTest(question=question):
                result = self.query(question)
                self.assertEqual(result['status'], Status.OUT_OF_SCOPE)
                self.assertNotIn('data', result)

    def test_model_response_shape_is_normalized(self):
        for body in [[], {'status': 'completed', 'output': [None]},
                     {'status': 'completed', 'output': [{'type': 'message', 'content': [None]}]}]:
            with self.subTest(body=body):
                model = OpenAIPlanModel(api_key='test-only', model='test-only',
                                        transport=lambda *a, **kw: io.BytesIO(json.dumps(body).encode()))
                try:
                    model.propose('9月净销售额')
                except ModelOutputInvalid:
                    continue
                except Exception as exc:
                    self.fail(f'Invalid model response escaped adapter: {exc}')
                self.fail('Invalid response accepted')

    def test_model_plan_validation_before_local_override(self):
        class Model:
            def propose(self, question):
                return {'metric': Metric.NET_SALES, 'date_start': '2026-09-01', 'date_end': '2026-09-30',
                        'group_by': ['forbidden'], 'filters': {}, 'sort': 'desc', 'comparison': 'none'}
        result = AgentWorkflow(self.service, model=Model(), mode='model').run({'question': '9月净销售额'})
        self.assertEqual(result['status'], Status.MODEL_OUTPUT_INVALID)

    def test_component_failure_never_returns_ratio(self):
        original = self.service.run
        def run(plan):
            if plan['metric'] == 'paid_amount':
                return {'status': Status.EXECUTION_FAILED, 'error': {'code': 'test_failure', 'message': 'failed'}}, 500
            return original(plan)
        self.service.run = run
        result = self.query('2026年9月退款率')
        self.assertEqual(result['status'], Status.EXECUTION_FAILED)
        self.assertNotIn('data', result)

    def test_missing_trace_never_returns_ratio(self):
        def unavailable(query_id):
            raise OSError('test trace failure')
        self.service.read_record = unavailable
        result = self.query('2026年9月客单价')
        self.assertEqual(result['status'], Status.EXECUTION_FAILED)
        self.assertNotIn('data', result)

    def test_forged_ranking_context_is_rejected(self):
        result = self.agent.run({'question': '9月销售额',
                                'context': {'ranking_limit': 'invalid'},
                                'clarification': {'id': 'clr_metric_001', 'choice': Metric.NET_SALES}})
        self.assertEqual(result['status'], Status.MODEL_OUTPUT_INVALID)

    def test_http_operations_real_platform(self):
        from agent import client as client_module
        from agent.operations import monthly_brief
        self.assertTrue(hasattr(client_module, 'HTTPAgentClient'), 'HTTP client not implemented')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = {**os.environ, 'PYTHONUTF8': '1', 'DATABRIDGE_AGENT_MODE': 'rules',
               'DATABRIDGE_DATABASE': str(self.service.database), 'DATABRIDGE_RECORDS': self.temp.name}
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'databridge.api:app',
                                        '--host', '127.0.0.1', '--port', str(port)],
                                       cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                client = client_module.HTTPAgentClient(f'http://127.0.0.1:{port}', timeout=2)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    probe = client.run({'question': '2026年9月净销售额'})
                    if probe['status'] == Status.SUCCESS:
                        break
                    if process.poll() is not None:
                        self.fail('Platform failed to start')
                    time.sleep(.1)
                brief = monthly_brief(client, '生成2026年9月经营简报')
                self.assertEqual(brief['status'], Status.SUCCESS)
                self.assertEqual(brief['largest_decline']['region'], '华南')
                self.assertEqual(brief['dataset_version'], 'demo-v1.1')
                cli = subprocess.run([sys.executable, 'scripts/run_operations_agent.py', '--api',
                                      f'http://127.0.0.1:{port}', '生成2026年9月经营简报'],
                                     cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', timeout=10)
                self.assertEqual(cli.returncode, 0, cli.stderr)
                self.assertEqual(json.loads(cli.stdout)['status'], Status.SUCCESS)
            finally:
                process.terminate()
                process.wait(timeout=10)
        # After termination a real connection failure must be understandable.
        result = client.run({'question': '2026年9月净销售额'})
        self.assertEqual(result['status'], Status.EXECUTION_FAILED)
        self.assertNotIn('data', result)

    def test_http_client_rejects_malformed_success(self):
        from agent import client as client_module
        self.assertTrue(hasattr(client_module, 'HTTPAgentClient'), 'HTTP client not implemented')
        for body in [[], {'status': 'success'}, {'status': 'success', 'data': []}]:
            client = client_module.HTTPAgentClient('http://127.0.0.1:8001',
                transport=lambda *a, **kw: io.BytesIO(json.dumps(body).encode()))
            result = client.run({'question': '9月净销售额'})
            self.assertEqual(result['status'], Status.EXECUTION_FAILED)
            self.assertNotIn('data', result)

    def test_operations_discloses_truncation(self):
        from agent.operations import monthly_brief
        response = self.query('2026年9月各地区净销售额环比')
        response['truncated'] = True
        class Gateway:
            def run(self, payload):
                return response
        result = monthly_brief(Gateway(), '生成2026年9月经营简报')
        self.assertEqual(result['status'], Status.INSUFFICIENT_DATA)
        self.assertNotIn('brief', result)

    def test_operations_missing_growth_rate_cannot_change_worst_region(self):
        from agent.operations import monthly_brief
        response = self.query('2026年9月各地区净销售额环比')
        next(r for r in response['data'] if r['region'] == '华南').pop('growth_rate')
        class Gateway:
            def run(self, payload):
                return response
        result = monthly_brief(Gateway(), '生成2026年9月经营简报')
        self.assertEqual(result['status'], Status.EXECUTION_FAILED)
        self.assertNotIn('brief', result)

    def test_growth_request_requires_basis_and_explicit_month_wins(self):
        for question in ['2026年9月净销售额增长率', '2026年9月客单价增长率']:
            with self.subTest(question=question):
                result = self.query(question)
                self.assertNotEqual(result['status'], Status.SUCCESS)
                self.assertNotIn('data', result)
        for question in ['2026年9月净销售额比上个月增长多少', '2026年9月客单价环比增长率', '本月净销售额比上月']:
            with self.subTest(question=question):
                result = self.query(question)
                self.assertEqual(result['status'], Status.SUCCESS)
                self.assertEqual(result['date_start'], '2026-09-01')
                self.assertEqual(result['plan']['comparison'], 'mom')

    def test_all_shared_synonyms_resolve_without_extra_clarification(self):
        for metric, spec in METRIC_SPEC.items():
            for term in spec['synonyms']:
                with self.subTest(metric=metric, term=term):
                    result = self.query('2026年9月' + term)
                    self.assertEqual(result['status'], Status.SUCCESS)
                    self.assertEqual(result['metric'], metric)
        result = self.query('2026年9月实付金额和人均支付金额')
        self.assertEqual(result['status'], Status.NEED_CLARIFICATION)


if __name__ == '__main__':
    unittest.main(verbosity=2)
