"""Regression checks for CSV auditing and atomic import behavior."""
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

from databridge.importer import QualityAudit, import_dataset
from databridge.service import QueryService


class ImporterTests(unittest.TestCase):
    EXPECTED = {
        'missing_column': 'MISSING_COLUMN',
        'duplicate_order_id': 'DUPLICATE_PRIMARY_KEY',
        'wrong_amount_type': 'INVALID_INTEGER',
        'missing_required_value': 'MISSING_REQUIRED_VALUE',
        'negative_amount': 'NEGATIVE_AMOUNT',
        'invalid_timestamp': 'INVALID_TIMESTAMP',
        'missing_foreign_key': 'MISSING_FOREIGN_KEY',
        'over_refund': 'REFUND_EXCEEDS_PAYMENT',
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='import-tests-', dir=ROOT / 'outputs')
        self.work = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_01_demo_passes_and_imports_exact_counts(self):
        target = self.work / 'demo.sqlite3'
        report = import_dataset(ROOT / 'data' / 'demo', target)
        self.assertEqual(report['status'], 'passed', report)
        self.assertTrue(target.is_file())
        with closing(sqlite3.connect(target)) as connection:
            counts = {table: connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                      for table in ('customers', 'orders', 'refunds')}
        self.assertEqual(counts, {'customers': 2000, 'orders': 20000, 'refunds': 3492})

    def test_02_isolated_errors_are_found_and_never_imported(self):
        for case, expected in self.EXPECTED.items():
            with self.subTest(case=case):
                target = self.work / f'{case}.sqlite3'
                report = import_dataset(ROOT / 'data' / 'anomalies' / case, target)
                codes = {item['code'] for item in report['issues'] if item['severity'] == 'error'}
                self.assertIn(expected, codes, report)
                self.assertGreater(report['error_count'], 0)
                self.assertFalse(target.exists())
                self.assertEqual(list(self.work.glob(target.name + '.tmp-*')), [])

    def test_03_large_amount_is_warning_and_remains_importable(self):
        target = self.work / 'warning.sqlite3'
        report = import_dataset(ROOT / 'data' / 'anomalies' / 'abnormal_amount_warning', target)
        self.assertEqual(report['status'], 'passed_with_warnings', report)
        self.assertEqual(report['error_count'], 0)
        self.assertIn('ABNORMAL_AMOUNT', {item['code'] for item in report['issues']})
        self.assertTrue(target.is_file())
        with closing(sqlite3.connect(target)) as connection:
            stored = connection.execute("SELECT code FROM data_quality_issues").fetchall()
        self.assertEqual(stored, [('ABNORMAL_AMOUNT',)])
        result, status = QueryService(target, self.work / 'warning-records').run({
            'metric': 'paid_amount', 'date_start': '2026-09-01', 'date_end': '2026-09-30',
            'dataset_version': 'small-v0.1'})
        self.assertEqual(status, 200)
        self.assertIn('ABNORMAL_AMOUNT', {item['code'] for item in result['warnings']})

    def test_04_existing_target_is_preserved(self):
        target = self.work / 'occupied.sqlite3'
        target.write_bytes(b'preserve-me')
        report = import_dataset(ROOT / 'data' / 'small', target)
        self.assertEqual(target.read_bytes(), b'preserve-me')
        self.assertIn('TARGET_EXISTS', {item['code'] for item in report['issues']})

    def test_05_missing_file_and_bad_metadata_are_reported(self):
        source = self.work / 'broken'
        source.mkdir()
        (source / 'metadata.json').write_text('{', encoding='utf-8')
        report = QualityAudit(source).run()
        codes = {item['code'] for item in report['issues']}
        self.assertIn('INVALID_METADATA', codes)
        self.assertIn('MISSING_FILE', codes)

    def test_06_source_csvs_are_not_modified(self):
        manifest = json.loads((ROOT / 'data' / 'demo' / 'manifest.json').read_text(encoding='utf-8'))
        import hashlib
        actual = {name: hashlib.sha256((ROOT / 'data' / 'demo' / name).read_bytes()).hexdigest()
                  for name in manifest['sha256']}
        self.assertEqual(actual, manifest['sha256'])

    def test_07_invalid_coverage_type_is_reported_without_crash(self):
        source = self.work / 'bad-coverage'
        shutil.copytree(ROOT / 'data' / 'small', source)
        metadata = json.loads((source / 'metadata.json').read_text(encoding='utf-8'))
        metadata['coverage_start'] = 123
        (source / 'metadata.json').write_text(json.dumps(metadata), encoding='utf-8')
        report = QualityAudit(source).run()
        self.assertIn('INVALID_TIMESTAMP', {item['code'] for item in report['issues']})
        self.assertGreater(report['error_count'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
