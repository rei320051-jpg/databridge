"""Contract, accounting, failure, and read-only regression checks."""
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from databridge.api import create_app
from databridge.service import QueryService, connect_readonly


class QueryApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = ROOT / 'outputs' / 'small-v0.1.sqlite3'
        cls.original_hash = hashlib.sha256(cls.database.read_bytes()).hexdigest()
        cls.temp = tempfile.TemporaryDirectory(prefix='api-tests-', dir=ROOT / 'outputs')
        cls.work = Path(cls.temp.name)
        cls.service = QueryService(cls.database, cls.work / 'records')
        cls.client = TestClient(create_app(cls.service))
        cls.expected = json.loads((ROOT / 'data' / 'small' / 'expected.json').read_text(encoding='utf-8'))['cases']

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        unchanged = hashlib.sha256(cls.database.read_bytes()).hexdigest() == cls.original_hash
        cls.temp.cleanup()
        if not unchanged:
            raise AssertionError('Original dataset was modified')

    def plan(self, **changes):
        return {'metric': 'net_sales', 'date_start': '2026-09-01',
                'date_end': '2026-09-30', 'dataset_version': 'small-v0.1'} | changes

    def query(self, **changes):
        response = self.client.post('/v1/query', json=self.plan(**changes))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_01_manual_cases_all_50_values(self):
        for case in self.expected:
            for metric, expected in case['expected'].items():
                with self.subTest(case=case['name'], metric=metric):
                    changes = {'metric': metric, 'date_start': case['date_start'], 'date_end': case['date_end']}
                    if 'region' in case:
                        changes['filters'] = {'region': [case['region']]}
                    result = self.query(**changes)
                    self.assertEqual(result['data'], [{metric: expected}])

    def test_02_regional_groups_and_sort(self):
        result = self.query(group_by=['region'])
        self.assertEqual(result['data'], [
            {'region': '华东', 'net_sales': 28000}, {'region': '华南', 'net_sales': 18000},
            {'region': '华北', 'net_sales': 8000}, {'region': '西部', 'net_sales': 5000}])
        self.assertEqual(self.query(group_by=['region'], sort='asc')['data'], result['data'][::-1])

    def test_03_refund_only_group_and_negative_net(self):
        result = self.query(date_start='2026-10-01', date_end='2026-10-31', group_by=['region'])
        self.assertEqual(result['data'], [{'region': '华东', 'net_sales': 7000},
                                          {'region': '华南', 'net_sales': -8000}])

    def test_04_customer_filters_and_two_dimensions(self):
        self.assertEqual(self.query(filters={'customer_type': ['new']})['data'], [{'net_sales': 23000}])
        self.assertEqual(self.query(group_by=['customer_type'])['data'], [
            {'customer_type': 'returning', 'net_sales': 36000}, {'customer_type': 'new', 'net_sales': 23000}])
        result = self.query(group_by=['region', 'customer_type'], filters={'region': ['华东', '华北'], 'customer_type': ['new']})
        self.assertEqual(result['data'], [
            {'region': '华东', 'customer_type': 'new', 'net_sales': 15000},
            {'region': '华北', 'customer_type': 'new', 'net_sales': 8000}])

    def test_05_limits_and_empty_groups(self):
        result = self.query(group_by=['region'], limit=1)
        self.assertEqual(len(result['data']), 1)
        self.assertTrue(result['truncated'])
        self.assertIn('RESULT_TRUNCATED', [item['code'] for item in result['warnings']])
        self.assertEqual(self.query(date_start='2026-09-07', date_end='2026-09-07', group_by=['region'])['data'], [])

    def test_06_invalid_plans_and_injection_are_rejected(self):
        invalid = [
            {'metric': 'unknown'}, {'sql': 'DELETE FROM orders'},
            {'filters': {'region': ["华东' OR 1=1 --"]}},
            {'filters': {'region': []}}, {'group_by': ['region', 'region']},
            {'date_start': '2026-02-30'}, {'date_start': '2026-10-01'},
            {'limit': True}, {'limit': 1001}, {'date_end': '9999-12-31'},
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                response = self.client.post('/v1/query', json=self.plan(**changes))
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()['status'], 'invalid_plan')
                self.assertIsNone(response.json()['data'])
        missing = self.plan()
        del missing['metric']
        self.assertEqual(self.client.post('/v1/query', json=missing).status_code, 422)
        malformed = self.client.post('/v1/query', content='{', headers={'Content-Type': 'application/json'})
        self.assertEqual(malformed.json()['status'], 'invalid_plan')
        self.assertEqual(self.client.post('/v1/query', json=[]).status_code, 422)

    def test_07_unknown_version_and_outside_coverage(self):
        unknown = self.client.post('/v1/query', json=self.plan(dataset_version='unknown'))
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(unknown.json()['status'], 'dataset_not_found')
        outside = self.client.post('/v1/query', json=self.plan(date_start='2026-07-01'))
        self.assertEqual(outside.status_code, 422)
        self.assertEqual(outside.json()['status'], 'insufficient_data')
        self.assertIsNone(outside.json()['data'])

    def test_08_comparison_global_and_group_union(self):
        result = self.query(compare={'date_start': '2026-08-01', 'date_end': '2026-08-31'})
        self.assertEqual(result['data'], [{'net_sales': 59000, 'compare_value': 10000,
                                           'difference': 49000, 'growth_rate': 4.9}])
        grouped = self.query(date_start='2026-10-01', date_end='2026-10-31', group_by=['region'],
                             compare={'date_start': '2026-09-01', 'date_end': '2026-09-30'})
        self.assertEqual(grouped['data'], [
            {'region': '华东', 'net_sales': 7000, 'compare_value': 28000, 'difference': -21000, 'growth_rate': -0.75},
            {'region': '华北', 'net_sales': 0, 'compare_value': 8000, 'difference': -8000, 'growth_rate': -1.0},
            {'region': '西部', 'net_sales': 0, 'compare_value': 5000, 'difference': -5000, 'growth_rate': -1.0},
            {'region': '华南', 'net_sales': -8000, 'compare_value': 18000, 'difference': -26000, 'growth_rate': -1.444444}])

    def test_08b_zero_comparison_base_returns_null_and_warning(self):
        result = self.query(date_start='2026-09-01', date_end='2026-09-30', group_by=['region'],
                            compare={'date_start': '2026-08-01', 'date_end': '2026-08-31'})
        south = next(row for row in result['data'] if row['region'] == '华南')
        self.assertEqual(south['compare_value'], 0)
        self.assertIsNone(south['growth_rate'])
        self.assertIn('NON_POSITIVE_COMPARISON_BASE', [item['code'] for item in result['warnings']])

    def test_08c_invalid_or_uncovered_comparison_is_rejected(self):
        reversed_period = self.client.post('/v1/query', json=self.plan(
            compare={'date_start': '2026-09-02', 'date_end': '2026-09-01'}))
        self.assertEqual(reversed_period.json()['error']['code'], 'REVERSED_DATE_RANGE')
        outside = self.client.post('/v1/query', json=self.plan(
            compare={'date_start': '2026-07-01', 'date_end': '2026-07-31'}))
        self.assertEqual(outside.json()['status'], 'insufficient_data')

    def test_09_trace_and_units(self):
        result = self.query(filters={'region': ['华东']})
        self.assertEqual(result['unit'], '分')
        self.assertEqual(result['display_divisor'], 100)
        record = self.client.get('/v1/query-records/' + result['query_id']).json()
        self.assertEqual(record['response'], result)
        self.assertGreaterEqual(record['elapsed_ms'], 0)
        aggregate_sql = record['sql'][-2:]
        self.assertNotIn('华东', aggregate_sql[0]['template'])
        self.assertIn('华东', aggregate_sql[0]['parameters'])
        self.assertNotIn('refunds', aggregate_sql[0]['template'])
        self.assertIn('refunds', aggregate_sql[1]['template'])
        self.assertEqual(self.client.get('/v1/query-records/not-a-uuid').status_code, 404)

    def test_10_database_write_and_other_tables_denied(self):
        connection = connect_readonly(self.database)
        try:
            for sql in ("UPDATE orders SET paid_amount_fen=0", 'DROP TABLE orders', 'SELECT * FROM sqlite_master', 'PRAGMA writable_schema=ON'):
                with self.subTest(sql=sql):
                    with self.assertRaises(sqlite3.DatabaseError):
                        connection.execute(sql)
        finally:
            connection.close()

    def test_11_missing_database_and_health(self):
        missing = self.work / 'absent.sqlite3'
        with TestClient(create_app(QueryService(missing, self.work / 'missing-records'))) as client:
            self.assertEqual(client.get('/health').status_code, 503)
            response = client.post('/v1/query', json=self.plan())
            self.assertEqual(response.status_code, 500)
            self.assertIsNone(response.json()['data'])
        self.assertFalse(missing.exists())
        self.assertEqual(self.client.get('/health').status_code, 200)

    def test_12_audit_failure_returns_no_success(self):
        occupied = self.work / 'occupied'
        occupied.write_text('test marker', encoding='utf-8')
        service = QueryService(self.database, occupied)
        result, status = service.run(self.plan())
        self.assertEqual(status, 500)
        self.assertIsNone(result['data'])
        self.assertEqual(result['error']['code'], 'AUDIT_WRITE_FAILED')

    def test_13_query_timeout_returns_no_results(self):
        large = self.work / 'timeout.sqlite3'
        shutil.copyfile(self.database, large)
        with closing(sqlite3.connect(large)) as writer:
            with writer:
                writer.executemany('INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)', [
                    (f'EXTRA{i}', 'C001', '华东', '2026-09-01T10:00:00', '2026-09-01T10:01:00', 'paid', 100, 'small-v0.1') for i in range(5000)])
            self.assertEqual(writer.execute('SELECT COUNT(*) FROM orders').fetchone()[0], 5012)
        service = QueryService(large, self.work / 'timeout-records', timeout_seconds=0.000001)
        result, status = service.run(self.plan())
        self.assertEqual(status, 504, result)
        self.assertEqual(result['status'], 'timeout')
        self.assertIsNone(result['data'])

    def test_14_global_customer_count_is_not_sum_of_group_counts(self):
        changed = self.work / 'cross-region.sqlite3'
        shutil.copyfile(self.database, changed)
        with closing(sqlite3.connect(changed)) as writer:
            with writer:
                writer.execute("UPDATE orders SET region='西部' WHERE order_id='O010'")
        service = QueryService(changed, self.work / 'cross-region-records')
        grouped, _ = service.run(self.plan(metric='paying_customers', group_by=['region']))
        total, _ = service.run(self.plan(metric='paying_customers'))
        self.assertEqual(sum(row['paying_customers'] for row in grouped['data']), 7)
        self.assertEqual(total['data'], [{'paying_customers': 6}])

    def test_15_mixed_dataset_versions_are_rejected(self):
        changed = self.work / 'mixed.sqlite3'
        shutil.copyfile(self.database, changed)
        with closing(sqlite3.connect(changed)) as writer:
            with writer:
                writer.execute("UPDATE orders SET dataset_version='other' WHERE order_id='O001'")
        result, status = QueryService(changed, self.work / 'mixed-records').run(self.plan())
        self.assertEqual(status, 422)
        self.assertEqual(result['error']['code'], 'DATASET_VERSION_MISMATCH')


if __name__ == '__main__':
    unittest.main(verbosity=2)
