"""Compose shared ratio metrics from two traceable read-only aggregates."""
from decimal import Decimal, ROUND_HALF_UP

from shared.contracts import Comparison, METRIC_SPEC, Status


def _rounded(value):
    return float(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def execute_ratio(workflow, slots, version, context):
    # Member 1's executor currently accepts only the five additive metrics.
    # Composition belongs to this gateway until native ratio support lands.
    from agent.workflow import _failure
    spec = METRIC_SPEC[slots['metric']]
    try:
        before = workflow.service.database.stat()
        fingerprint = (before.st_ino, before.st_size, before.st_mtime_ns)
    except OSError:
        return _failure(Status.EXECUTION_FAILED, '正式数据集尚未导入。', version,
                        'database_unavailable', ['已导入的数据集'], '先导入数据集。', True)
    responses = []
    for metric in (spec['numerator'], spec['denominator']):
        result = workflow._execute({**slots, 'metric': metric}, version, {**context, 'metric': metric})
        if result['status'] != Status.SUCCESS:
            return result
        responses.append(result)
    try:
        after = workflow.service.database.stat()
        changed = fingerprint != (after.st_ino, after.st_size, after.st_mtime_ns)
    except OSError:
        changed = True
    if changed or any(r['dataset_version'] != version or r['truncated'] for r in responses):
        return _failure(Status.EXECUTION_FAILED, '分量查询期间数据集改变或结果不完整。', version,
                        'inconsistent_components', ['一致且完整的分量'], '固定数据集后重试。', True)
    numerator, denominator = responses
    dimensions = slots['group_by']
    key = lambda row: tuple(row[d] for d in dimensions)
    nrows = {key(r): r for r in numerator['data']}
    drows = {key(r): r for r in denominator['data']}
    warnings = numerator['warnings'] + [w for w in denominator['warnings'] if w not in numerator['warnings']]
    data = []
    scale = Decimal(100 if spec['unit'] == '%' else 1)

    def ratio(n, d, label):
        if d <= 0:
            warnings.append({'level': 'warning', 'code': 'NON_POSITIVE_DENOMINATOR',
                             'message': f'{label}分母为零，指标为空。', 'impact': '不得把空值解释为 0。'})
            return None
        return _rounded(Decimal(str(n)) / Decimal(str(d)) * scale)

    for group in sorted(nrows.keys() | drows.keys()):
        nrow, drow = nrows.get(group, {}), drows.get(group, {})
        n, d = nrow.get(spec['numerator'], 0), drow.get(spec['denominator'], 0)
        value = ratio(n, d, str(group or '整体'))
        row = {**dict(zip(dimensions, group)), slots['metric']: value,
               'numerator_value': n, 'denominator_value': d}
        if slots['comparison'] == Comparison.MOM:
            bn, bd = nrow.get('compare_value', 0), drow.get('compare_value', 0)
            base = ratio(bn, bd, str(group or '整体') + '基期')
            delta = _rounded(Decimal(str(value)) - Decimal(str(base))) if value is not None and base is not None else None
            growth = delta / base if delta is not None and base is not None and base > 0 else None
            if growth is None:
                warnings.append({'level': 'warning', 'code': 'NON_POSITIVE_COMPARISON_BASE',
                                 'message': '比率基期为空或不大于零，增长率为空。', 'impact': '不参与降幅排名。'})
            row.update(compare_value=base, difference=delta, growth_rate=growth,
                       compare_numerator_value=bn, compare_denominator_value=bd)
        data.append(row)
    # Nulls always sort last, independently of direction.
    valid = [r for r in data if r[slots['metric']] is not None]
    valid.sort(key=lambda r: r[slots['metric']], reverse=slots['sort'] == 'desc')
    data = valid + [r for r in data if r[slots['metric']] is None]
    return {**numerator, 'data': data, 'columns': list(data[0]) if data else dimensions + [slots['metric']],
            'metric': slots['metric'], 'unit': spec['unit'], 'definition': spec['definition'],
            'metric_kind': 'ratio', 'components': {'numerator_metric': spec['numerator'],
                'denominator_metric': spec['denominator'], 'rule': '先汇总分子分母，再相除；分母为零时返回 null'},
            'component_query_ids': [r['query_id'] for r in responses],
            'generated_sql': '\n'.join(r['generated_sql'] for r in responses),
            'sql_parameters': [p for r in responses for p in r['sql_parameters']],
            'source_tables': sorted(set(numerator['source_tables'] + denominator['source_tables'])),
            'warnings': warnings, 'row_count': len(data), 'context': context,
            'plan': {k: slots[k] for k in numerator['plan']},
            'message': f"已按「{spec['label']}」口径组合可信分量；数据来自正式模拟数据集。"}
