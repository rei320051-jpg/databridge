"""Call the generated demo database through an actual short-lived HTTP server."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    expected = json.loads((ROOT / 'data' / 'demo' / 'expected.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='demo-http-', dir=ROOT / 'outputs') as temporary:
        environment = os.environ.copy()
        environment['DATABRIDGE_DATABASE'] = str(ROOT / 'outputs' / 'demo-v1.1.sqlite3')
        environment['DATABRIDGE_RECORDS'] = str(Path(temporary) / 'records')
        process = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'databridge.api:app', '--host', '127.0.0.1',
             '--port', str(port), '--log-level', 'warning'], cwd=ROOT, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=8, trust_env=False) as client:
                deadline = time.perf_counter() + 12
                response = None
                while time.perf_counter() < deadline:
                    require(process.poll() is None, 'Demo API process exited during startup')
                    try:
                        response = client.get('/health')
                        if response.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                require(response is not None and response.status_code == 200, 'Demo API did not become ready')
                plan = {'metric': 'net_sales', 'date_start': '2026-09-01', 'date_end': '2026-09-30',
                        'dataset_version': 'demo-v1.1', 'group_by': ['region']}
                current = client.post('/v1/query', json=plan)
                require(current.status_code == 200, current.text)
                current_data = current.json()
                wanted = {region: metrics['net_sales'] for region, metrics in expected['september_by_region'].items()}
                actual = {row['region']: row['net_sales'] for row in current_data['data']}
                require(actual == wanted, 'Demo regional results differ from independent expectations')
                compared = client.post('/v1/query', json=plan | {
                    'compare': {'date_start': '2026-08-01', 'date_end': '2026-08-31'}})
                require(compared.status_code == 200, compared.text)
                require(all({'compare_value', 'difference', 'growth_rate'} <= set(row)
                            for row in compared.json()['data']), 'Comparison fields missing')
                record = client.get('/v1/query-records/' + compared.json()['query_id'])
                require(record.status_code == 200 and record.json()['response'] == compared.json(), 'Trace mismatch')
                evidence = {'status': 'passed', 'transport': 'actual HTTP over localhost',
                            'dataset_version': 'demo-v1.1', 'health': response.json(),
                            'september_by_region': current_data, 'comparison': compared.json(),
                            'trace_sql_count': len(record.json()['sql'])}
                (ROOT / 'outputs' / 'demo-http-smoke.json').write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                print('PASS demo database via real HTTP, comparison, and trace retrieval')
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                output, _ = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                output, _ = process.communicate(timeout=5)
            if output:
                print(output.decode('utf-8', errors='replace').strip())
            print('Demo smoke-test server stopped')


if __name__ == '__main__':
    main()
