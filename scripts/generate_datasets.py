"""Deterministically generate fictional demo data and isolated anomaly fixtures."""
import csv
import hashlib
import json
import random
import shutil
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMALL = ROOT / 'data' / 'small'
DEMO = ROOT / 'data' / 'demo'
ANOMALIES = ROOT / 'data' / 'anomalies'
SEED = 20260929
VERSION = 'demo-v1.0'
REGIONS = ('华东', '华南', '华北', '西部')


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator='\n', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def stamp(moment):
    return moment.strftime('%Y-%m-%dT%H:%M:%S')


def add_expected(bucket, order=None, refund=None):
    if order:
        bucket['paid_orders'].add(order['order_id'])
        bucket['paying_customers'].add(order['customer_id'])
        bucket['paid_amount'] += order['paid_amount_fen']
    if refund:
        bucket['successful_refund_amount'] += refund['refund_amount_fen']


def finish_expected(bucket):
    paid = bucket['paid_amount']
    refunded = bucket['successful_refund_amount']
    return {'paid_orders': len(bucket['paid_orders']),
            'paying_customers': len(bucket['paying_customers']),
            'paid_amount': paid, 'successful_refund_amount': refunded,
            'net_sales': paid - refunded}


def fresh_bucket():
    return {'paid_orders': set(), 'paying_customers': set(), 'paid_amount': 0,
            'successful_refund_amount': 0}


def generate_demo():
    randomizer = random.Random(SEED)
    start = datetime(2026, 1, 1)
    end = datetime(2026, 10, 1)
    customers = []
    for index in range(1, 2001):
        created = datetime(2024, 1, 1) + timedelta(days=randomizer.randrange(730), seconds=randomizer.randrange(86400))
        customers.append({'customer_id': f'C{index:05d}',
                          'customer_type': 'new' if index % 4 == 0 else 'returning',
                          'created_at': stamp(created), 'dataset_version': VERSION})
    orders = []
    paid_orders = []
    for index in range(1, 20001):
        # Reserve the maximum payment delay so successful payment never escapes coverage.
        ordered = start + timedelta(seconds=randomizer.randrange(int((end - start).total_seconds()) - 1800))
        draw = randomizer.random()
        status = 'paid' if draw < 0.88 else ('cancelled' if draw < 0.95 else 'failed')
        amount = randomizer.randint(100, 2000000) if status == 'paid' else 0
        paid_at = stamp(ordered + timedelta(minutes=randomizer.randint(1, 30))) if status == 'paid' else ''
        row = {'order_id': f'O{index:06d}',
               'customer_id': customers[randomizer.randrange(len(customers))]['customer_id'],
               'region': randomizer.choices(REGIONS, weights=(40, 25, 20, 15), k=1)[0],
               'ordered_at': stamp(ordered), 'paid_at': paid_at,
               'payment_status': status, 'paid_amount_fen': amount,
               'dataset_version': VERSION}
        orders.append(row)
        if status == 'paid':
            paid_orders.append(row)
    refunds = []
    refund_index = 1
    for order in paid_orders:
        if order['paid_amount_fen'] <= 0 or randomizer.random() >= 0.17:
            continue
        parts = 2 if order['paid_amount_fen'] >= 2 and randomizer.random() < 0.12 else 1
        total = randomizer.randint(1, order['paid_amount_fen'])
        if total < 2:
            parts = 1
        amounts = [total] if parts == 1 else [randomizer.randint(1, total - 1), 0]
        if parts == 2:
            amounts[1] = total - amounts[0]
        requested = datetime.strptime(order['paid_at'], '%Y-%m-%dT%H:%M:%S') + timedelta(days=randomizer.randint(0, 25))
        for amount in amounts:
            status = randomizer.choices(('success', 'failed', 'pending'), weights=(88, 6, 6), k=1)[0]
            completed = requested + timedelta(hours=randomizer.randint(1, 72))
            # Keep every fixture event inside the declared complete coverage.
            if completed >= end:
                completed = end - timedelta(seconds=1)
                requested = min(requested, completed)
            refunds.append({'refund_id': f'R{refund_index:06d}', 'order_id': order['order_id'],
                            'requested_at': stamp(requested),
                            'refunded_at': stamp(completed) if status == 'success' else '',
                            'refund_status': status, 'refund_amount_fen': amount,
                            'dataset_version': VERSION})
            refund_index += 1
            requested = completed + timedelta(minutes=1)
    metadata = {
        'dataset_version': VERSION, 'is_simulated': True, 'timezone': 'Asia/Shanghai',
        'coverage_start': stamp(start), 'coverage_end_exclusive': stamp(end),
        'generation_method': f'Deterministic fictional generator; seed={SEED}.',
        'limitations': 'Synthetic distributions are for demonstration and performance tests only; they do not represent a real retailer.'
    }
    DEMO.mkdir(parents=True, exist_ok=True)
    (DEMO / 'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    write_csv(DEMO / 'customers.csv', ['customer_id', 'customer_type', 'created_at', 'dataset_version'], customers)
    write_csv(DEMO / 'orders.csv', ['order_id', 'customer_id', 'region', 'ordered_at', 'paid_at',
                                    'payment_status', 'paid_amount_fen', 'dataset_version'], orders)
    write_csv(DEMO / 'refunds.csv', ['refund_id', 'order_id', 'requested_at', 'refunded_at',
                                     'refund_status', 'refund_amount_fen', 'dataset_version'], refunds)

    all_by_month = defaultdict(fresh_bucket)
    by_month_region = defaultdict(fresh_bucket)
    orders_by_id = {row['order_id']: row for row in orders}
    for order in paid_orders:
        month = order['paid_at'][:7]
        add_expected(all_by_month[month], order=order)
        add_expected(by_month_region[(month, order['region'])], order=order)
    for refund in refunds:
        if refund['refund_status'] != 'success':
            continue
        month = refund['refunded_at'][:7]
        region = orders_by_id[refund['order_id']]['region']
        add_expected(all_by_month[month], refund=refund)
        add_expected(by_month_region[(month, region)], refund=refund)
    expected = {
        'calculation': 'Independent aggregation performed while generating rows; amounts are fen.',
        'monthly': {month: finish_expected(all_by_month[month]) for month in sorted(all_by_month)},
        'september_by_region': {region: finish_expected(by_month_region[('2026-09', region)]) for region in REGIONS},
    }
    (DEMO / 'expected.json').write_text(json.dumps(expected, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    hashes = {}
    for name in ('metadata.json', 'customers.csv', 'orders.csv', 'refunds.csv', 'expected.json'):
        hashes[name] = hashlib.sha256((DEMO / name).read_bytes()).hexdigest()
    manifest = {'seed': SEED, 'dataset_version': VERSION,
                'row_counts': {'customers': len(customers), 'orders': len(orders), 'refunds': len(refunds)},
                'status_counts': {
                    'paid_orders': sum(row['payment_status'] == 'paid' for row in orders),
                    'cancelled_orders': sum(row['payment_status'] == 'cancelled' for row in orders),
                    'failed_orders': sum(row['payment_status'] == 'failed' for row in orders),
                    'successful_refunds': sum(row['refund_status'] == 'success' for row in refunds),
                    'failed_refunds': sum(row['refund_status'] == 'failed' for row in refunds),
                    'pending_refunds': sum(row['refund_status'] == 'pending' for row in refunds),
                }, 'sha256': hashes}
    (DEMO / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest


def read_csv(path):
    with path.open(encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def write_case(name, mutate):
    target = ANOMALIES / name
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SMALL / 'metadata.json', target / 'metadata.json')
    tables = {}
    for table in ('customers', 'orders', 'refunds'):
        fields, rows = read_csv(SMALL / f'{table}.csv')
        tables[table] = [list(fields), rows]
    mutate(tables)
    for table, (fields, rows) in tables.items():
        write_csv(target / f'{table}.csv', fields, rows)


def generate_anomalies():
    if ANOMALIES.exists():
        shutil.rmtree(ANOMALIES)
    cases = {
        'missing_column': lambda t: t['orders'][0].remove('region'),
        'duplicate_order_id': lambda t: t['orders'][1].append(dict(t['orders'][1][0])),
        'wrong_amount_type': lambda t: t['orders'][1][1].__setitem__('paid_amount_fen', 'abc'),
        'missing_required_value': lambda t: t['orders'][1][1].__setitem__('region', ''),
        'negative_amount': lambda t: t['orders'][1][1].__setitem__('paid_amount_fen', '-1'),
        'invalid_timestamp': lambda t: t['orders'][1][1].__setitem__('paid_at', '2026-99-99T00:00:00'),
        'missing_foreign_key': lambda t: t['orders'][1][1].__setitem__('customer_id', 'C999'),
        'abnormal_amount_warning': lambda t: t['orders'][1][1].__setitem__('paid_amount_fen', '999999999'),
        'over_refund': lambda t: t['refunds'][1][0].__setitem__('refund_amount_fen', '999999'),
    }
    for name, mutate in cases.items():
        write_case(name, mutate)
    (ANOMALIES / 'README.md').write_text(
        '# 异常测试数据\n\n每个子目录是一个独立数据集，只包含一种主要异常，均由small-v0.1复制后确定性修改。'
        '前七种及over_refund应阻止导入；abnormal_amount_warning应允许导入并给出警告。\n', encoding='utf-8')
    return sorted(cases)


if __name__ == '__main__':
    manifest = generate_demo()
    cases = generate_anomalies()
    print(json.dumps({'demo': manifest['row_counts'], 'anomaly_cases': cases}, ensure_ascii=False))
