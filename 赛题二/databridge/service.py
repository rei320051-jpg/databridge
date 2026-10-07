"""Validated plans execute fixed, parameterized SQL against one read-only dataset."""
import json
import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
GROUP_FIELDS = {'region': 'o.region', 'customer_type': 'c.customer_type'}
PAID_FORMULAS = {
    'paid_orders': 'COUNT(DISTINCT o.order_id)',
    'paying_customers': 'COUNT(DISTINCT o.customer_id)',
    'paid_amount': 'COALESCE(SUM(o.paid_amount_fen), 0)',
    'net_sales': 'COALESCE(SUM(o.paid_amount_fen), 0)',
}
TABLES = {'orders', 'refunds', 'customers', 'dataset_metadata', 'data_quality_issues'}


class QueryError(Exception):
    def __init__(self, status, code, message, http_status=422):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.http_status = http_status

    def response(self, query_id=None):
        result = {'status': self.status, 'data': None,
                  'error': {'code': self.code, 'message': self.message}, 'warnings': []}
        if query_id:
            result['query_id'] = query_id
        return result


def allow_reads(action, table, column, database, trigger):
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_TRANSACTION):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and table in TABLES:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def connect_readonly(path, timeout_seconds=2.0):
    if not path.is_file():
        raise QueryError('execution_failed', 'DATABASE_UNAVAILABLE',
                         '数据集数据库尚未准备好，请先运行样例构建程序', 500)
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True,
                                 timeout=timeout_seconds)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only = ON')
    connection.execute('PRAGMA foreign_keys = ON')
    deadline = time.perf_counter() + timeout_seconds
    connection.set_progress_handler(lambda: int(time.perf_counter() >= deadline), 1000)
    connection.set_authorizer(allow_reads)
    return connection


class QueryService:
    def __init__(self, database=None, records=None, timeout_seconds=2.0):
        self.database = Path(database) if database is not None else ROOT / 'outputs' / 'small-v0.1.sqlite3'
        self.records = Path(records) if records is not None else ROOT / 'outputs' / 'query_records'
        self.timeout_seconds = timeout_seconds
        schema = json.loads((ROOT / 'contracts' / 'query_plan.schema.json').read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())
        self.dictionary = json.loads((ROOT / 'config' / 'metrics.json').read_text(encoding='utf-8'))
        self.metrics = {item['id']: item for item in self.dictionary['metrics']}

    @staticmethod
    def period_bounds(date_start, date_end, label='查询'):
        if date_start > date_end:
            raise QueryError('invalid_plan', 'REVERSED_DATE_RANGE', f'{label}开始日期不能晚于结束日期')
        try:
            end = date.fromisoformat(date_end) + timedelta(days=1)
        except (ValueError, OverflowError):
            raise QueryError('invalid_plan', 'INVALID_DATE_RANGE', f'{label}结束日期无法转换为查询边界') from None
        return date_start + 'T00:00:00', end.isoformat() + 'T00:00:00'

    def validate(self, raw):
        errors = sorted(self.validator.iter_errors(raw), key=lambda error: str(list(error.path)))
        if errors:
            location = '.'.join(str(part) for part in errors[0].path) or 'request'
            raise QueryError('invalid_plan', 'INVALID_QUERY_PLAN',
                             f'查询计划字段不合法：{location}；请检查必填字段、日期、取值及额外字段')
        plan = dict(raw)
        for field, default in [('group_by', []), ('filters', {}), ('sort', 'desc'), ('limit', 100)]:
            plan.setdefault(field, default)
        current = self.period_bounds(plan['date_start'], plan['date_end'])
        comparison = None
        if 'compare' in plan:
            comparison = self.period_bounds(plan['compare']['date_start'], plan['compare']['date_end'], '对比期')
        return plan, current, comparison

    def check_dataset(self, connection, plan, periods, execute):
        rows = execute('SELECT * FROM dataset_metadata', []).fetchall()
        if len(rows) != 1:
            raise QueryError('insufficient_data', 'INVALID_DATASET_METADATA', '数据库必须包含且仅包含一个数据集版本')
        meta = dict(rows[0])
        if meta['dataset_version'] != plan['dataset_version']:
            raise QueryError('dataset_not_found', 'DATASET_NOT_FOUND', '当前数据库没有请求的数据版本', 404)
        if meta['timezone'] != self.dictionary['timezone']:
            raise QueryError('insufficient_data', 'TIMEZONE_MISMATCH', '数据集时区与指标配置不一致')
        for label, (low, high) in periods:
            if low < meta['coverage_start'] or high > meta['coverage_end_exclusive']:
                raise QueryError('insufficient_data', 'OUTSIDE_COVERAGE', f'{label}超出数据集覆盖范围')
        for table in ('orders', 'refunds', 'customers'):
            mismatch = execute(f'SELECT 1 FROM {table} WHERE dataset_version != ? LIMIT 1',
                               [plan['dataset_version']]).fetchone()
            if mismatch:
                raise QueryError('insufficient_data', 'DATASET_VERSION_MISMATCH', '业务表存在不一致的数据版本')
        quality = execute("SELECT code, message, table_name, row_number, field_name FROM data_quality_issues WHERE severity = 'warning' ORDER BY issue_id LIMIT 100", []).fetchall()
        meta['_quality_warnings'] = [dict(row) for row in quality]
        return meta

    def aggregate(self, plan, low, high, execute, refunds=False):
        dimensions = [GROUP_FIELDS[field] for field in plan['group_by']]
        select_dims = [f'{GROUP_FIELDS[field]} AS {field}' for field in plan['group_by']]
        needs_customer = 'customer_type' in plan['group_by'] or 'customer_type' in plan['filters']
        if refunds:
            table_clause = 'refunds r JOIN orders o ON o.order_id = r.order_id'
            formula = 'COALESCE(SUM(r.refund_amount_fen), 0)'
            where = ["r.refund_status = 'success'", 'r.refunded_at >= ?', 'r.refunded_at < ?']
        else:
            table_clause = 'orders o'
            formula = PAID_FORMULAS[plan['metric']]
            where = ["o.payment_status = 'paid'", 'o.paid_at >= ?', 'o.paid_at < ?']
        if needs_customer:
            table_clause += ' JOIN customers c ON c.customer_id = o.customer_id'
        parameters = [low, high]
        for field in ('region', 'customer_type'):
            if field in plan['filters']:
                values = plan['filters'][field]
                where.append(f"{GROUP_FIELDS[field]} IN ({','.join('?' for _ in values)})")
                parameters.extend(values)
        selection = ', '.join(select_dims + [formula + ' AS value'])
        sql = f"SELECT {selection} FROM {table_clause} WHERE {' AND '.join(where)}"
        if dimensions:
            sql += ' GROUP BY ' + ', '.join(dimensions)
        rows = execute(sql, parameters).fetchall()
        return {tuple(row[field] for field in plan['group_by']): row['value'] for row in rows}

    def metric_values(self, plan, low, high, execute):
        paid = {} if plan['metric'] == 'successful_refund_amount' else self.aggregate(plan, low, high, execute)
        refunds = self.aggregate(plan, low, high, execute, refunds=True) if plan['metric'] in ('net_sales', 'successful_refund_amount') else {}
        keys = paid.keys() | refunds.keys()
        if plan['metric'] == 'net_sales':
            return {key: paid.get(key, 0) - refunds.get(key, 0) for key in keys}
        if plan['metric'] == 'successful_refund_amount':
            return refunds
        return paid

    def run(self, raw):
        query_id = str(uuid4())
        started = time.perf_counter()
        trace = []
        record = {'query_id': query_id, 'request': raw, 'sql': trace}
        connection = None
        error = None
        try:
            plan, current_period, comparison_period = self.validate(raw)
            record['plan'] = plan
            connection = connect_readonly(self.database, self.timeout_seconds)
            connection.execute('BEGIN')  # One consistent snapshot for both event aggregates.

            def execute(sql, parameters):
                trace.append({'template': sql, 'parameters': parameters})
                return connection.execute(sql, parameters)

            periods = [('查询期', current_period)]
            if comparison_period:
                periods.append(('对比期', comparison_period))
            meta = self.check_dataset(connection, plan, periods, execute)
            current = self.metric_values(plan, *current_period, execute)
            rows = []
            warnings = [{'code': 'SIMULATED_DATA', 'message': '当前数据集为虚构模拟数据'}] if meta['is_simulated'] else []
            warnings.extend({'code': item['code'], 'message': item['message'], 'source': 'data_quality',
                             'table': item['table_name'], 'row': item['row_number'], 'field': item['field_name']}
                            for item in meta['_quality_warnings'])
            if comparison_period:
                comparison = self.metric_values(plan, *comparison_period, execute)
                non_positive_base = False
                for key in sorted(current.keys() | comparison.keys()):
                    value, base = current.get(key, 0), comparison.get(key, 0)
                    growth = None if base <= 0 else round((value - base) / base, 6)
                    non_positive_base = non_positive_base or base <= 0
                    rows.append(dict(zip(plan['group_by'], key)) | {
                        plan['metric']: value, 'compare_value': base,
                        'difference': value - base, 'growth_rate': growth})
                if non_positive_base:
                    warnings.append({'code': 'NON_POSITIVE_COMPARISON_BASE',
                                     'message': '部分对比期数值为0或负数，增长率无法按常规比例计算，已返回null'})
            else:
                rows = [dict(zip(plan['group_by'], key)) | {plan['metric']: value}
                        for key, value in sorted(current.items())]
            rows.sort(key=lambda row: row[plan['metric']], reverse=plan['sort'] == 'desc')
            truncated = len(rows) > plan['limit']
            if truncated:
                warnings.append({'code': 'RESULT_TRUNCATED', 'message': '分组结果已按limit截断，请提高limit取得完整结果'})
            metric = self.metrics[plan['metric']]
            sources = ['orders']
            if plan['metric'] in ('net_sales', 'successful_refund_amount'):
                sources.append('refunds')
            if 'customer_type' in plan['group_by'] or 'customer_type' in plan['filters']:
                sources.append('customers')
            result = {
                'status': 'success', 'query_id': query_id, 'metric': plan['metric'],
                'data': rows[:plan['limit']], 'definition': metric['definition'], 'unit': metric['unit'],
                'display_unit': metric.get('display_unit', metric['unit']),
                'display_divisor': metric.get('display_divisor', 1),
                'date_start': plan['date_start'], 'date_end': plan['date_end'],
                'compare': plan.get('compare'),
                'timezone': meta['timezone'], 'group_by': plan['group_by'], 'filters': plan['filters'],
                'source_tables': sources, 'dataset_version': meta['dataset_version'],
                'dictionary_version': self.dictionary['dictionary_version'],
                'warnings': warnings, 'truncated': truncated,
            }
            http_status = 200
        except QueryError as caught:
            error = caught
        except sqlite3.Error as caught:
            record['internal_error'] = str(caught)
            error = QueryError('timeout', 'QUERY_TIMEOUT', '查询超过运行时限', 504) if 'interrupted' in str(caught).lower() else QueryError('execution_failed', 'DATABASE_EXECUTION_FAILED', '数据库查询失败，请查看查询记录', 500)
        finally:
            if connection is not None:
                connection.close()
        if error:
            result, http_status = error.response(query_id), error.http_status
        record['status'] = result['status']
        record['response'] = result
        record['elapsed_ms'] = round((time.perf_counter() - started) * 1000, 3)
        try:
            self.records.mkdir(parents=True, exist_ok=True)
            with (self.records / f'{query_id}.json').open('x', encoding='utf-8') as handle:
                json.dump(record, handle, ensure_ascii=False, indent=2)
        except OSError:
            return QueryError('execution_failed', 'AUDIT_WRITE_FAILED', '查询记录无法保存，请检查输出目录权限', 500).response(), 500
        return result, http_status

    def read_record(self, query_id):
        try:
            canonical = str(UUID(query_id))
        except (ValueError, AttributeError):
            raise QueryError('query_not_found', 'QUERY_NOT_FOUND', '查询记录不存在', 404) from None
        if canonical != query_id:
            raise QueryError('query_not_found', 'QUERY_NOT_FOUND', '查询记录不存在', 404)
        try:
            return json.loads((self.records / f'{canonical}.json').read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise QueryError('query_not_found', 'QUERY_NOT_FOUND', '查询记录不存在', 404) from None
