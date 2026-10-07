"""Validate generated demo data against independent expectations and benchmark queries."""
import hashlib
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from databridge.service import QueryService


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def percentile(values, percent):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percent))]


def main():
    demo = ROOT / 'data' / 'demo'
    database = ROOT / 'outputs' / 'demo-v1.1.sqlite3'
    expected = json.loads((demo / 'expected.json').read_text(encoding='utf-8'))
    manifest = json.loads((demo / 'manifest.json').read_text(encoding='utf-8'))
    actual_hashes = {name: hashlib.sha256((demo / name).read_bytes()).hexdigest()
                     for name in manifest['sha256']}
    require(actual_hashes == manifest['sha256'], 'Demo source checksums changed')
    checks = 0
    with tempfile.TemporaryDirectory(prefix='demo-validation-', dir=ROOT / 'outputs') as temporary:
        service = QueryService(database, Path(temporary) / 'records')

        def run(plan):
            result, status = service.run(plan)
            require(status == 200, f'Query failed: {result}')
            return result

        for month, metrics in expected['monthly'].items():
            # Derive exact inclusive month end without depending on calendar shortcuts.
            from datetime import date, timedelta
            year, number = map(int, month.split('-'))
            next_month = date(year + 1, 1, 1) if number == 12 else date(year, number + 1, 1)
            plan = {'date_start': month + '-01', 'date_end': (next_month - timedelta(days=1)).isoformat(),
                    'dataset_version': manifest['dataset_version']}
            for metric, value in metrics.items():
                result = run(plan | {'metric': metric})
                require(result['data'] == [{metric: value}], f'{month} {metric} mismatch')
                checks += 1
        for metric in ('paid_orders', 'paying_customers', 'paid_amount', 'successful_refund_amount', 'net_sales'):
            result = run({'metric': metric, 'date_start': '2026-09-01', 'date_end': '2026-09-30',
                          'dataset_version': manifest['dataset_version'], 'group_by': ['region']})
            actual = {row['region']: row[metric] for row in result['data']}
            wanted = {region: values[metric] for region, values in expected['september_by_region'].items()}
            require(actual == wanted, f'September regional {metric} mismatch')
            checks += len(wanted)

        plans = [
            {'metric': 'paid_orders', 'date_start': '2026-01-01', 'date_end': '2026-09-30'},
            {'metric': 'net_sales', 'date_start': '2026-09-01', 'date_end': '2026-09-30', 'group_by': ['region']},
            {'metric': 'paying_customers', 'date_start': '2026-01-01', 'date_end': '2026-09-30', 'group_by': ['region', 'customer_type']},
            {'metric': 'successful_refund_amount', 'date_start': '2026-07-01', 'date_end': '2026-09-30', 'group_by': ['region']},
            {'metric': 'net_sales', 'date_start': '2026-09-01', 'date_end': '2026-09-30', 'group_by': ['region'],
             'compare': {'date_start': '2026-08-01', 'date_end': '2026-08-31'}},
        ]
        plans = [plan | {'dataset_version': manifest['dataset_version']} for plan in plans]
        for plan in plans:
            run(plan)
        durations = []
        for _ in range(20):
            for plan in plans:
                started = time.perf_counter()
                run(plan)
                durations.append((time.perf_counter() - started) * 1000)
    report = {
        'status': 'passed', 'dataset_version': manifest['dataset_version'],
        'row_counts': manifest['row_counts'], 'expected_value_checks': checks,
        'benchmark': {'queries': len(durations), 'includes_audit_record_write': True,
                      'median_ms': round(statistics.median(durations), 3),
                      'p95_ms': round(percentile(durations, 0.95), 3),
                      'max_ms': round(max(durations), 3)},
        'scope': 'Local development computer; five representative query shapes; not a load or concurrency test.'
    }
    output = ROOT / 'outputs' / 'demo-validation.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
