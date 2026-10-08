"""Frozen inspect contract backed by the formal importer's checks, without activation."""
import csv
import hashlib
import io
import json
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from databridge.importer import PRIMARY_KEYS, TABLE_FIELDS, TIME_FORMAT, QualityAudit


def inspect_csv_files(uploads):
    tables, issues = {}, []
    digest = hashlib.sha256()

    def issue(code, message, table='跨表', field='*', level='error'):
        issues.append({'level': level, 'code': code, 'table': table, 'field': field,
                       'count': 1, 'message': message,
                       'impact': '严重问题需修复后才能导入；质检不会修改或切换当前查询库。'})

    for filename, raw in sorted(uploads):
        # Filename is used only for classification, never as a filesystem path.
        name = filename.lower()
        matches = [table for table in TABLE_FIELDS if table.rstrip('s') in name]
        if len(matches) != 1 or not name.endswith('.csv'):
            issue('UNKNOWN_TABLE', '文件名需包含 order / refund / customer，且为 CSV')
            continue
        table = matches[0]
        if table in tables:
            issue('DUPLICATE_TABLE', f'{table}只能上传一份', table)
            continue
        try:
            text = raw.decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
            rows = list(reader)
            tables[table] = (raw, reader.fieldnames or [], rows)
            digest.update(table.encode() + b'\0' + raw + b'\0')
        except (UnicodeDecodeError, csv.Error):
            issue('INVALID_CSV', 'CSV必须是合法UTF-8编码和CSV格式', table)

    for table in TABLE_FIELDS:
        if table not in tables:
            issue('MISSING_TABLE', f'缺少{table}.csv', table)
    versions = {row.get('dataset_version') for _, _, rows in tables.values() for row in rows}
    version = next(iter(versions)) if len(versions) == 1 and None not in versions and '' not in versions else None
    if not version:
        issue('VERSION_MISMATCH', '三张正式表必须有同一个非空dataset_version')
    version = version or 'upload-' + digest.hexdigest()[:16]

    # CSV-only inspection does not imply coverage completeness. Use observed
    # event bounds solely to run importer checks, and explicitly warn callers.
    events = []
    for table, field in [('orders', 'paid_at'), ('refunds', 'refunded_at')]:
        for row in tables.get(table, (None, None, []))[2]:
            try:
                event = datetime.strptime(row.get(field) or '', TIME_FORMAT)
                if event.strftime(TIME_FORMAT) == row[field]:
                    events.append(event)
            except (ValueError, TypeError):
                pass
    low = min(events) if events else datetime(2026, 1, 1)
    try:
        high = max(events) + timedelta(seconds=1) if events else low + timedelta(days=1)
    except OverflowError:
        high = datetime.max.replace(microsecond=0)
    metadata = {'dataset_version': version, 'is_simulated': False, 'timezone': 'Asia/Shanghai',
                'coverage_start': low.strftime(TIME_FORMAT),
                'coverage_end_exclusive': high.strftime(TIME_FORMAT)}
    with tempfile.TemporaryDirectory(prefix='databridge-inspect-') as folder:
        source = Path(folder)
        for table, (raw, _, _) in tables.items():
            (source / f'{table}.csv').write_bytes(raw)
        (source / 'metadata.json').write_text(json.dumps(metadata), encoding='utf-8')
        audit = QualityAudit(source)
        report = audit.run()
    for item in report['issues']:
        issue(item['code'], item['message'], item.get('table', '跨表'),
              item.get('field', '*'), item['severity'])
    issue('COVERAGE_NOT_DECLARED', 'CSV质检不证明时间覆盖完整；导入前须另备metadata.json声明覆盖区间、时区及模拟标记。',
          level='warning')
    table_reports = []
    for table, (_, headers, rows) in tables.items():
        local = [item for item in issues if item['table'] == table]
        types = {field: ('数值' if field.endswith('_fen') else '时间' if field.endswith('_at') else '文本')
                 for field in headers}
        counts = Counter(item['level'] for item in local)
        table_reports.append({'name': table, 'rows': len(rows), 'columns': len(headers),
                              'primary_key': PRIMARY_KEYS[table], 'field_types': types,
                              'issues': local, 'error_count': counts['error'],
                              'warning_count': counts['warning']})
    counts = Counter(item['level'] for item in issues)
    return {'status': 'ok', 'dataset_version': version, 'tables': table_reports,
            'cross_table_issues': [item for item in issues if item['table'] == '跨表' or
                                   item['code'] in ('MISSING_FOREIGN_KEY', 'REFUND_EXCEEDS_PAYMENT')],
            'issues': issues, 'total_errors': counts['error'], 'total_warnings': counts['warning'],
            'inspected_at': datetime.now(timezone.utc).isoformat()}
