"""Verify the fictional fixture against manual answers, SQL, and plain Python.

This is a development verifier, not the production CSV importer/query service.
"""
import argparse
import csv
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'small'
TIME_FORMAT = '%Y-%m-%dT%H:%M:%S'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def read_table(name):
    with (DATA / f'{name}.csv').open(encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key, value in row.items():
            if key.endswith('_fen'):
                row[key] = int(value)
            elif key.endswith('_at'):
                if value:
                    parsed = datetime.strptime(value, TIME_FORMAT)
                    require(parsed.strftime(TIME_FORMAT) == value, f'Bad timestamp: {value}')
                else:
                    row[key] = None
    return rows


def validate_relations(tables, meta):
    customers = {row['customer_id']: row for row in tables['customers']}
    orders = {row['order_id']: row for row in tables['orders']}
    success_amounts = defaultdict(int)
    for rows in tables.values():
        for row in rows:
            require(row['dataset_version'] == meta['dataset_version'], 'Version mismatch')
    for row in orders.values():
        customer = customers[row['customer_id']]
        require(customer['created_at'] <= row['ordered_at'], 'Customer created after order')
        if row['paid_at']:
            require(meta['coverage_start'] <= row['paid_at'] < meta['coverage_end_exclusive'], 'Payment outside coverage')
    for row in tables['refunds']:
        order = orders[row['order_id']]
        require(order['payment_status'] == 'paid', 'Refund on unpaid order')
        require(row['requested_at'] >= order['paid_at'], 'Refund requested before payment')
        if row['refund_status'] == 'success':
            require(meta['coverage_start'] <= row['refunded_at'] < meta['coverage_end_exclusive'], 'Refund outside coverage')
            success_amounts[row['order_id']] += row['refund_amount_fen']
    for order_id, amount in success_amounts.items():
        require(amount <= orders[order_id]['paid_amount_fen'], f'Excess refund: {order_id}')


def bounds(case, meta):
    start = datetime.strptime(case['date_start'], '%Y-%m-%d')
    end = datetime.strptime(case['date_end'], '%Y-%m-%d') + timedelta(days=1)
    low, high = start.strftime(TIME_FORMAT), end.strftime(TIME_FORMAT)
    require(low < high, 'Reversed date range')
    require(meta['coverage_start'] <= low and high <= meta['coverage_end_exclusive'], 'Insufficient data coverage')
    return low, high


def calculate_sql(connection, low, high, region):
    # Aggregate each event stream independently; never sum orders after a 1:N join.
    paid_orders, customers, paid = connection.execute('''
        SELECT COUNT(DISTINCT order_id), COUNT(DISTINCT customer_id),
               COALESCE(SUM(paid_amount_fen), 0)
        FROM orders
        WHERE payment_status = 'paid' AND paid_at >= ? AND paid_at < ?
          AND (? IS NULL OR region = ?)
    ''', (low, high, region, region)).fetchone()
    refund = connection.execute('''
        SELECT COALESCE(SUM(r.refund_amount_fen), 0)
        FROM refunds r JOIN orders o ON o.order_id = r.order_id
        WHERE r.refund_status = 'success' AND r.refunded_at >= ? AND r.refunded_at < ?
          AND (? IS NULL OR o.region = ?)
    ''', (low, high, region, region)).fetchone()[0]
    return dict(paid_orders=paid_orders, paying_customers=customers,
                paid_amount=paid, successful_refund_amount=refund, net_sales=paid-refund)


def calculate_python(tables, low, high, region):
    orders = {row['order_id']: row for row in tables['orders']}
    paid_rows = [row for row in orders.values()
                 if row['payment_status'] == 'paid' and low <= row['paid_at'] < high
                 and (region is None or row['region'] == region)]
    refund_rows = [row for row in tables['refunds']
                   if row['refund_status'] == 'success' and low <= row['refunded_at'] < high
                   and (region is None or orders[row['order_id']]['region'] == region)]
    paid = sum(row['paid_amount_fen'] for row in paid_rows)
    refund = sum(row['refund_amount_fen'] for row in refund_rows)
    return dict(paid_orders=len({row['order_id'] for row in paid_rows}),
                paying_customers=len({row['customer_id'] for row in paid_rows}),
                paid_amount=paid, successful_refund_amount=refund, net_sales=paid-refund)


def check_constraints(connection):
    attempts = [
        ('duplicate primary key', "INSERT INTO customers SELECT * FROM customers WHERE customer_id='C001'"),
        ('missing foreign key', "UPDATE orders SET customer_id='MISSING' WHERE order_id='O002'"),
        ('negative amount', "UPDATE orders SET paid_amount_fen=-1 WHERE order_id='O002'"),
        ('missing payment time', "UPDATE orders SET paid_at=NULL WHERE order_id='O002'"),
        ('refund missing completion', "UPDATE refunds SET refunded_at=NULL WHERE refund_id='R001'"),
    ]
    for name, sql in attempts:
        connection.execute('SAVEPOINT invalid_case')
        rejected = False
        try:
            connection.execute(sql)
        except sqlite3.IntegrityError:
            rejected = True
        finally:
            connection.execute('ROLLBACK TO invalid_case')
            connection.execute('RELEASE invalid_case')
        require(rejected, f'Constraint failed to reject: {name}')
    return len(attempts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build-db', action='store_true', help='Create outputs/small.sqlite3; refuse existing file')
    args = parser.parse_args()
    meta = read_json(DATA / 'metadata.json')
    tables = {name: read_table(name) for name in ('customers', 'orders', 'refunds')}
    validate_relations(tables, meta)
    connection = sqlite3.connect(':memory:')
    connection.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
    connection.execute('INSERT INTO dataset_metadata VALUES (?, ?, ?, ?, ?)',
                       (meta['dataset_version'], int(meta['is_simulated']), meta['timezone'],
                        meta['coverage_start'], meta['coverage_end_exclusive']))
    for table, rows in tables.items():
        # Identifiers come only from the three fixed fixture table names/header whitelist.
        columns = [row[1] for row in connection.execute(f'PRAGMA table_info({table})')]
        require(list(rows[0]) == columns, f'Unexpected fixture columns: {table}')
        placeholders = ','.join('?' for _ in columns)
        connection.executemany(f'INSERT INTO {table} VALUES ({placeholders})',
                               [tuple(row[column] for column in columns) for row in rows])
    connection.commit()
    require(connection.execute('PRAGMA foreign_key_check').fetchall() == [], 'Foreign key failures')
    metric_ids = {metric['id'] for metric in read_json(ROOT / 'config' / 'metrics.json')['metrics']}
    cases = read_json(DATA / 'expected.json')['cases']
    for case in cases:
        require(set(case['expected']) == metric_ids, 'Metric dictionary mismatch')
        low, high = bounds(case, meta)
        actual = calculate_sql(connection, low, high, case.get('region'))
        independent = calculate_python(tables, low, high, case.get('region'))
        require(actual == independent == case['expected'], f"Mismatch in {case['name']}: SQL={actual}, Python={independent}, expected={case['expected']}")
        print(f"PASS {case['name']}")
    rejected = check_constraints(connection)
    try:
        bounds({'date_start': '2026-07-01', 'date_end': '2026-07-31'}, meta)
    except ValueError:
        print('PASS outside coverage rejected')
    else:
        raise ValueError('Outside coverage was not rejected')
    if args.build_db:
        output = ROOT / 'outputs' / 'small-v0.1.sqlite3'
        output.parent.mkdir(exist_ok=True)
        # Reserve a new file only; never replace a user database.
        with output.open('xb'):
            pass
        with sqlite3.connect(output) as destination:
            connection.backup(destination)
        print(f'Database created: {output}')
    connection.close()
    print(f'PASS {len(cases)} cases x 5 metrics; {rejected} database constraints; 1 coverage rejection')


if __name__ == '__main__':
    main()
