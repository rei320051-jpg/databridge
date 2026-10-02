"""Strict CSV quality checks and atomic SQLite import for DataBridge datasets."""
import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
TIME_FORMAT = '%Y-%m-%dT%H:%M:%S'
INTEGER = re.compile(r'^(0|-?[1-9][0-9]*)$')
TABLE_FIELDS = {
    'customers': ['customer_id', 'customer_type', 'created_at', 'dataset_version'],
    'orders': ['order_id', 'customer_id', 'region', 'ordered_at', 'paid_at',
               'payment_status', 'paid_amount_fen', 'dataset_version'],
    'refunds': ['refund_id', 'order_id', 'requested_at', 'refunded_at',
                'refund_status', 'refund_amount_fen', 'dataset_version'],
}
PRIMARY_KEYS = {'customers': 'customer_id', 'orders': 'order_id', 'refunds': 'refund_id'}
NULLABLE = {'orders': {'paid_at'}, 'refunds': {'refunded_at'}, 'customers': set()}


class QualityAudit:
    def __init__(self, source, config=None):
        self.source = Path(source)
        self.config = config or json.loads((ROOT / 'config' / 'data_quality.json').read_text(encoding='utf-8'))
        self.issues = []
        self.rows = {}
        self.metadata = None
        self.row_counts = {}

    def issue(self, severity, code, message, table=None, row=None, field=None):
        if len(self.issues) < self.config['max_reported_issues']:
            item = {'severity': severity, 'code': code, 'message': message}
            if table is not None:
                item['table'] = table
            if row is not None:
                item['row'] = row
            if field is not None:
                item['field'] = field
            self.issues.append(item)

    def parse_time(self, value, table, row, field):
        try:
            parsed = datetime.strptime(value, TIME_FORMAT)
            if parsed.strftime(TIME_FORMAT) != value:
                raise ValueError
            return value
        except (TypeError, ValueError):
            self.issue('error', 'INVALID_TIMESTAMP', f'{field}必须是YYYY-MM-DDTHH:MM:SS', table, row, field)
            return None

    def parse_integer(self, value, table, row, field):
        if not isinstance(value, str) or not INTEGER.fullmatch(value):
            self.issue('error', 'INVALID_INTEGER', f'{field}必须是十进制整数', table, row, field)
            return None
        return int(value)

    def read_metadata(self):
        path = self.source / 'metadata.json'
        try:
            metadata = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            self.issue('error', 'MISSING_FILE', '缺少metadata.json')
            return
        except (OSError, json.JSONDecodeError):
            self.issue('error', 'INVALID_METADATA', 'metadata.json无法读取或不是合法JSON')
            return
        required = {'dataset_version', 'is_simulated', 'timezone', 'coverage_start', 'coverage_end_exclusive'}
        missing = required - set(metadata) if isinstance(metadata, dict) else required
        if missing:
            self.issue('error', 'MISSING_METADATA_FIELD', '缺少元数据字段：' + ', '.join(sorted(missing)))
            return
        if not isinstance(metadata['dataset_version'], str) or not metadata['dataset_version'].strip():
            self.issue('error', 'INVALID_DATASET_VERSION', 'dataset_version必须是非空字符串')
        if type(metadata['is_simulated']) is not bool:
            self.issue('error', 'INVALID_SIMULATION_FLAG', 'is_simulated必须是布尔值')
        if metadata['timezone'] != self.config['timezone']:
            self.issue('error', 'INVALID_TIMEZONE', f"timezone必须是{self.config['timezone']}")
        low = self.parse_time(metadata['coverage_start'], 'metadata', 1, 'coverage_start')
        high = self.parse_time(metadata['coverage_end_exclusive'], 'metadata', 1, 'coverage_end_exclusive')
        metadata['coverage_start'], metadata['coverage_end_exclusive'] = low, high
        if low and high and low >= high:
            self.issue('error', 'INVALID_COVERAGE', '数据覆盖开始时间必须早于结束时间')
        self.metadata = metadata

    def read_table(self, table):
        path = self.source / f'{table}.csv'
        try:
            handle = path.open(encoding='utf-8-sig', newline='')
        except OSError:
            self.issue('error', 'MISSING_FILE', f'缺少或无法读取{table}.csv', table)
            self.rows[table], self.row_counts[table] = [], 0
            return
        with handle:
            reader = csv.DictReader(handle)
            headers = reader.fieldnames
            expected = TABLE_FIELDS[table]
            if headers is None:
                self.issue('error', 'MISSING_HEADER', 'CSV缺少表头', table)
                self.rows[table], self.row_counts[table] = [], 0
                return
            duplicates = [name for name, count in Counter(headers).items() if count > 1]
            if duplicates:
                self.issue('error', 'DUPLICATE_COLUMN', '重复字段：' + ', '.join(duplicates), table)
            missing = [name for name in expected if name not in headers]
            extra = [name for name in headers if name not in expected]
            if missing:
                self.issue('error', 'MISSING_COLUMN', '缺少必需字段：' + ', '.join(missing), table)
            if extra:
                self.issue('warning', 'UNEXPECTED_COLUMN', '未使用字段：' + ', '.join(extra), table)
            rows = []
            seen = set()
            raw_count = 0
            for number, raw in enumerate(reader, start=2):
                raw_count += 1
                if None in raw:
                    self.issue('error', 'EXTRA_CSV_VALUE', '该行字段数超过表头', table, number)
                clean = {}
                valid = True
                for field in expected:
                    value = raw.get(field)
                    if value is None:
                        valid = False
                        continue
                    if value == '' and field not in NULLABLE[table]:
                        self.issue('error', 'MISSING_REQUIRED_VALUE', f'{field}不能为空', table, number, field)
                        valid = False
                    clean[field] = value if value != '' else None
                primary = raw.get(PRIMARY_KEYS[table])
                if primary:
                    if primary in seen:
                        self.issue('error', 'DUPLICATE_PRIMARY_KEY', f'重复主键：{primary}', table, number, PRIMARY_KEYS[table])
                        valid = False
                    seen.add(primary)
                if valid:
                    rows.append((number, clean))
            self.rows[table], self.row_counts[table] = rows, raw_count
            if table in ('customers', 'orders') and not rows:
                self.issue('error', 'EMPTY_REQUIRED_TABLE', f'{table}至少需要一行数据', table)

    def validate_rows(self):
        if self.metadata is None:
            return
        version = self.metadata.get('dataset_version')
        low, high = self.metadata.get('coverage_start'), self.metadata.get('coverage_end_exclusive')
        regions = set(self.config['allowed_regions'])
        customer_types = set(self.config['allowed_customer_types'])
        payment_statuses = set(self.config['allowed_payment_statuses'])
        refund_statuses = set(self.config['allowed_refund_statuses'])
        threshold = self.config['amount_warning_threshold_fen']
        customers, orders, refunds = {}, {}, []
        for number, row in self.rows.get('customers', []):
            if row['dataset_version'] != version:
                self.issue('error', 'VERSION_MISMATCH', '行版本与metadata不一致', 'customers', number, 'dataset_version')
            if row['customer_type'] not in customer_types:
                self.issue('error', 'INVALID_ENUM', '未知客户类型', 'customers', number, 'customer_type')
            created = self.parse_time(row['created_at'], 'customers', number, 'created_at')
            if created:
                customers[row['customer_id']] = row
        for number, row in self.rows.get('orders', []):
            if row['dataset_version'] != version:
                self.issue('error', 'VERSION_MISMATCH', '行版本与metadata不一致', 'orders', number, 'dataset_version')
            if row['region'] not in regions:
                self.issue('error', 'INVALID_ENUM', '未知地区', 'orders', number, 'region')
            if row['payment_status'] not in payment_statuses:
                self.issue('error', 'INVALID_ENUM', '未知支付状态', 'orders', number, 'payment_status')
            ordered = self.parse_time(row['ordered_at'], 'orders', number, 'ordered_at')
            paid = self.parse_time(row['paid_at'], 'orders', number, 'paid_at') if row['paid_at'] else None
            amount = self.parse_integer(str(row['paid_amount_fen']), 'orders', number, 'paid_amount_fen')
            row['paid_amount_fen'] = amount
            if amount is not None:
                if amount < 0:
                    self.issue('error', 'NEGATIVE_AMOUNT', '实付金额不能为负数', 'orders', number, 'paid_amount_fen')
                if amount > threshold:
                    self.issue('warning', 'ABNORMAL_AMOUNT', f'实付金额超过警告阈值{threshold}分', 'orders', number, 'paid_amount_fen')
            if row['payment_status'] == 'paid':
                if not paid:
                    self.issue('error', 'INCONSISTENT_STATUS', '成功支付必须有支付时间', 'orders', number, 'paid_at')
            elif row['paid_at'] is not None or amount not in (0, None):
                self.issue('error', 'INCONSISTENT_STATUS', '未成功支付必须没有支付时间且金额为0', 'orders', number)
            if ordered and paid and paid < ordered:
                self.issue('error', 'INVALID_TIME_ORDER', '支付时间早于下单时间', 'orders', number, 'paid_at')
            if paid and low and high and not (low <= paid < high):
                self.issue('error', 'OUTSIDE_COVERAGE', '支付事件超出声明覆盖区间', 'orders', number, 'paid_at')
            customer = customers.get(row['customer_id'])
            if customer is None:
                self.issue('error', 'MISSING_FOREIGN_KEY', '客户编号不存在', 'orders', number, 'customer_id')
            elif ordered and customer['created_at'] > ordered:
                self.issue('error', 'INVALID_TIME_ORDER', '客户建立时间晚于下单时间', 'orders', number, 'ordered_at')
            orders[row['order_id']] = row
        successful = defaultdict(int)
        for number, row in self.rows.get('refunds', []):
            if row['dataset_version'] != version:
                self.issue('error', 'VERSION_MISMATCH', '行版本与metadata不一致', 'refunds', number, 'dataset_version')
            if row['refund_status'] not in refund_statuses:
                self.issue('error', 'INVALID_ENUM', '未知退款状态', 'refunds', number, 'refund_status')
            requested = self.parse_time(row['requested_at'], 'refunds', number, 'requested_at')
            refunded = self.parse_time(row['refunded_at'], 'refunds', number, 'refunded_at') if row['refunded_at'] else None
            amount = self.parse_integer(str(row['refund_amount_fen']), 'refunds', number, 'refund_amount_fen')
            row['refund_amount_fen'] = amount
            if amount is not None:
                if amount <= 0:
                    self.issue('error', 'NON_POSITIVE_AMOUNT', '退款金额必须为正数', 'refunds', number, 'refund_amount_fen')
                if amount > threshold:
                    self.issue('warning', 'ABNORMAL_AMOUNT', f'退款金额超过警告阈值{threshold}分', 'refunds', number, 'refund_amount_fen')
            if row['refund_status'] == 'success':
                if not refunded:
                    self.issue('error', 'INCONSISTENT_STATUS', '成功退款必须有完成时间', 'refunds', number, 'refunded_at')
            elif row['refunded_at'] is not None:
                self.issue('error', 'INCONSISTENT_STATUS', '失败或处理中退款不能有完成时间', 'refunds', number, 'refunded_at')
            if requested and refunded and refunded < requested:
                self.issue('error', 'INVALID_TIME_ORDER', '退款完成时间早于申请时间', 'refunds', number, 'refunded_at')
            if refunded and low and high and not (low <= refunded < high):
                self.issue('error', 'OUTSIDE_COVERAGE', '成功退款事件超出声明覆盖区间', 'refunds', number, 'refunded_at')
            order = orders.get(row['order_id'])
            if order is None:
                self.issue('error', 'MISSING_FOREIGN_KEY', '订单编号不存在', 'refunds', number, 'order_id')
            elif order['payment_status'] != 'paid':
                self.issue('error', 'REFUND_UNPAID_ORDER', '退款只能关联成功支付订单', 'refunds', number, 'order_id')
            elif requested and order['paid_at'] and requested < order['paid_at']:
                self.issue('error', 'INVALID_TIME_ORDER', '退款申请时间早于支付时间', 'refunds', number, 'requested_at')
            if row['refund_status'] == 'success' and amount is not None:
                successful[row['order_id']] += amount
            refunds.append(row)
        for order_id, amount in successful.items():
            order = orders.get(order_id)
            if order and order['paid_amount_fen'] is not None and amount > order['paid_amount_fen']:
                self.issue('error', 'REFUND_EXCEEDS_PAYMENT', f'{order_id}累计成功退款超过实付金额', 'refunds')

    def run(self):
        self.read_metadata()
        for table in TABLE_FIELDS:
            self.read_table(table)
        self.validate_rows()
        counts = Counter(item['severity'] for item in self.issues)
        return {
            'status': 'failed' if counts['error'] else ('passed_with_warnings' if counts['warning'] else 'passed'),
            'source': str(self.source.resolve()), 'quality_rule_version': self.config['version'],
            'dataset_version': self.metadata.get('dataset_version') if self.metadata else None,
            'row_counts': self.row_counts, 'error_count': counts['error'],
            'warning_count': counts['warning'], 'issues': self.issues,
            'issues_truncated': len(self.issues) >= self.config['max_reported_issues'],
        }


def import_dataset(source, target):
    audit = QualityAudit(source)
    report = audit.run()
    if report['error_count']:
        return report
    target = Path(target)
    if target.exists():
        report['status'] = 'failed'
        report['error_count'] += 1
        report['issues'].append({'severity': 'error', 'code': 'TARGET_EXISTS',
                                 'message': '目标数据库已存在，拒绝覆盖'})
        return report
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + f'.tmp-{uuid4()}')
    connection = None
    try:
        connection = sqlite3.connect(temporary)
        connection.execute('PRAGMA foreign_keys = ON')
        connection.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
        metadata = audit.metadata
        connection.execute('INSERT INTO dataset_metadata VALUES (?, ?, ?, ?, ?)',
                           (metadata['dataset_version'], int(metadata['is_simulated']), metadata['timezone'],
                            metadata['coverage_start'], metadata['coverage_end_exclusive']))
        for table, fields in TABLE_FIELDS.items():
            marks = ','.join('?' for _ in fields)
            connection.executemany(f'INSERT INTO {table} VALUES ({marks})',
                                   [tuple(row[field] for field in fields) for _, row in audit.rows[table]])
        warnings = [item for item in report['issues'] if item['severity'] == 'warning']
        connection.executemany(
            'INSERT INTO data_quality_issues (severity, code, message, table_name, row_number, field_name) VALUES (?, ?, ?, ?, ?, ?)',
            [(item['severity'], item['code'], item['message'], item.get('table'), item.get('row'), item.get('field'))
             for item in warnings])
        if connection.execute('PRAGMA foreign_key_check').fetchall():
            raise sqlite3.IntegrityError('foreign key check failed')
        connection.commit()
        connection.close()
        connection = None
        # On Windows rename fails if a target appeared after the earlier check;
        # unlike replace(), it never overwrites that file.
        temporary.rename(target)
        report['database'] = str(target.resolve())
        return report
    except (OSError, sqlite3.Error) as error:
        if connection is not None:
            connection.close()
        if temporary.exists():
            temporary.unlink()
        report['status'] = 'failed'
        report['error_count'] += 1
        report['issues'].append({'severity': 'error', 'code': 'IMPORT_FAILED',
                                 'message': f'数据库导入失败：{type(error).__name__}'})
        return report
