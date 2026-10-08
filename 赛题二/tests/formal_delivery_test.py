"""Offline regressions for formal startup, frozen inspection and real Streamlit -> HTTP."""
import json
import os
import socket
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))

from fastapi.testclient import TestClient
from databridge.api import app, create_app
from databridge.service import QueryService
from client import BackendError, QueryClient


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = QueryService(ROOT / 'outputs/demo-v1.1.sqlite3', Path(self.temp.name))
        with patch.dict(os.environ, {'DATABRIDGE_AGENT_MODE': 'rules'}):
            self.client = TestClient(create_app(self.service))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def upload(self, source, changes=None):
        files = [(table + '.csv', (source / (table + '.csv')).read_bytes())
                 for table in ('orders', 'refunds', 'customers')]
        if changes:
            files = changes(files)
        return self.client.post('/datasets/inspect', files=[('files', (name, raw, 'text/csv'))
                                                          for name, raw in files])

    def test_default_api_uses_formal_demo(self):
        with TestClient(app) as client:
            health = client.get('/health').json()
        self.assertEqual(health['status'], 'ok')
        self.assertEqual(health['dataset_version'], 'demo-v1.1')
        self.assertEqual(health['row_counts']['orders'], 20000)
        self.assertEqual(health['coverage_start'], '2026-01-01T00:00:00')

    def test_invalid_database_never_reports_ready(self):
        bad = Path(self.temp.name) / 'bad.sqlite3'
        bad.write_bytes(b'not a database')
        for database in (bad, bad.with_name('missing.sqlite3')):
            with TestClient(create_app(QueryService(database))) as client:
                response = client.get('/health')
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()['dataset_version'], 'unavailable')

    def test_formal_csv_inspect_has_frozen_shape_and_never_activates(self):
        before = self.client.get('/health').json()
        result = self.upload(ROOT / 'data/small')
        self.assertEqual(result.status_code, 200)
        report = result.json()
        self.assertEqual(report['total_errors'], 0, report)
        self.assertEqual(report['dataset_version'], 'small-v0.1')
        self.assertEqual({table['name'] for table in report['tables']}, {'orders', 'refunds', 'customers'})
        self.assertTrue(all('impact' in item for item in report['issues']))
        self.assertIn('COVERAGE_NOT_DECLARED', {item['code'] for item in report['issues']})
        self.assertEqual(self.client.get('/health').json(), before)

    def test_anomalies_match_formal_importer(self):
        cases = {'negative_amount': 'NEGATIVE_AMOUNT', 'over_refund': 'REFUND_EXCEEDS_PAYMENT',
                 'duplicate_order_id': 'DUPLICATE_PRIMARY_KEY', 'invalid_timestamp': 'INVALID_TIMESTAMP',
                 'missing_foreign_key': 'MISSING_FOREIGN_KEY', 'wrong_amount_type': 'INVALID_INTEGER',
                 'missing_required_value': 'MISSING_REQUIRED_VALUE', 'missing_column': 'MISSING_COLUMN'}
        for case, code in cases.items():
            with self.subTest(case=case):
                report = self.upload(ROOT / 'data/anomalies' / case).json()
                self.assertGreater(report['total_errors'], 0)
                self.assertIn(code, {item['code'] for item in report['issues']})

    def test_missing_duplicate_unknown_and_bad_encoding(self):
        edits = [lambda f: f[:1], lambda f: [f[0], f[0]],
                 lambda f: [('unknown.csv', b'x\n1\n')],
                 lambda f: [('orders.csv', b'\xff')]]
        for edit in edits:
            self.assertGreater(self.upload(ROOT / 'data/small', edit).json()['total_errors'], 0)

    def test_path_filename_cannot_write_outside_temp(self):
        report = self.upload(ROOT / 'data/small', lambda files: [
            ('../../' + name, raw) for name, raw in files]).json()
        self.assertEqual(report['total_errors'], 0, report)

    def test_limits(self):
        response = self.client.post('/datasets/inspect', files=[('files', ('orders.csv', b'x'))] * 4)
        self.assertEqual(response.status_code, 422)
        response = self.client.post('/datasets/inspect', files=[('files', ('orders.csv', b'x' * (20 * 1024 * 1024 + 1)))])
        self.assertEqual(response.status_code, 413)

    def test_live_client_blocks_unactivated_data(self):
        client = QueryClient('live')
        client.query_block_reason = 'not activated'
        with self.assertRaisesRegex(BackendError, 'not activated'):
            client.submit('9月净销售额')
        with self.assertRaisesRegex(BackendError, 'not activated'):
            client.resolve_clarification({}, 'net_sales', '9月销售额')

    def test_package_rejects_stale_database_even_with_same_version_and_count(self):
        from scripts.build_submission import validate_prebuilt_database
        target = Path(self.temp.name) / 'small.sqlite3'
        shutil.copyfile(ROOT / 'outputs/small-v0.1.sqlite3', target)
        validate_prebuilt_database(target, ROOT / 'data/small')
        with closing(sqlite3.connect(target)) as connection:
            connection.execute('UPDATE orders SET paid_amount_fen=paid_amount_fen+1 WHERE paid_amount_fen>0')
            connection.commit()
        with self.assertRaisesRegex(SystemExit, '不一致'):
            validate_prebuilt_database(target, ROOT / 'data/small')

    def test_http_ratios_and_clarification(self):
        for question in ('2026年9月净销售额', '2026年9月退款率', '2026年9月客单价', '2026年9月支付人均消费'):
            response = self.client.post('/agent/query', json={'question': question, 'dataset_version': 'demo-v1.1'}).json()
            self.assertEqual(response['status'], 'success', response)
        first = self.client.post('/agent/query', json={'question': '9月销售额'}).json()
        self.assertEqual(first['status'], 'need_clarification')
        response = self.client.post('/agent/query', json={'question': '9月销售额',
            'context': first['clarification']['resolved_context'],
            'clarification': {'id': first['clarification']['id'], 'choice': 'net_sales'}}).json()
        self.assertEqual(response['status'], 'success')

    def test_real_streamlit_page_queries_formal_http_three_times(self):
        import uvicorn
        from streamlit.testing.v1 import AppTest
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        with patch.dict(os.environ, {'DATABRIDGE_AGENT_MODE': 'rules'}):
            server = uvicorn.Server(uvicorn.Config(create_app(self.service), log_level='error'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(server.started)
            with patch.dict(os.environ, {'DATABRIDGE_BACKEND': 'live',
                                        'DATABRIDGE_API': f'http://127.0.0.1:{port}'}):
                page = AppTest.from_file(str(ROOT / 'app/app.py'), default_timeout=40).run()
                self.assertFalse(page.exception, str(page.exception))
                source = next(r for r in page.radio if r.label == '未上传文件时使用的内置数据集')
                source.set_value(source.options[1]).run()
                self.assertFalse(page.exception, str(page.exception))
                expected = json.loads((ROOT / 'data/demo/expected.json').read_text(encoding='utf-8'))['monthly']['2026-09']['net_sales'] / 100
                for _ in range(3):
                    box = next(item for item in page.text_input if item.label == '用自然语言提问')
                    box.set_value('2026年9月净销售额')
                    next(button for button in page.button if button.label == '提问').click().run()
                    self.assertFalse(page.exception, str(page.exception))
                    response = page.session_state['last_response']
                    self.assertEqual(response['status'], 'success', response)
                    self.assertEqual(response['dataset_version'], 'demo-v1.1')
                    self.assertEqual(response['data'][0]['net_sales'], expected)
                source = next(r for r in page.radio if r.label == '未上传文件时使用的内置数据集')
                page.session_state['agent_result'] = {'status': 'success', 'dataset_version': 'demo-v1.1'}
                source.set_value(source.options[0]).run()
                self.assertEqual(page.session_state['history'], [])
                self.assertIsNone(page.session_state['agent_result'])
                self.assertFalse(any(button.label == '提问' for button in page.button))
                source = next(r for r in page.radio if r.label == '未上传文件时使用的内置数据集')
                self.service.database = ROOT / 'outputs/small-v0.1.sqlite3'
                source.set_value(source.options[1]).run()
                self.assertFalse(page.exception, str(page.exception))
                self.assertFalse(any(button.label == '提问' for button in page.button))
        finally:
            server.should_exit = True
            thread.join(10)
            sock.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
