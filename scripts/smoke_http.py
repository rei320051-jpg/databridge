"""Start a short-lived local server, call it over HTTP, save actual evidence, stop it."""
import json
import socket
import subprocess
import sys
import time
from decimal import Decimal
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
    base = f'http://127.0.0.1:{port}'
    process = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'databridge.api:app', '--host', '127.0.0.1',
         '--port', str(port), '--log-level', 'warning'],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
    )
    evidence = {'transport': 'actual HTTP over localhost', 'base_url': base, 'responses': {}}
    try:
        with httpx.Client(base_url=base, timeout=5, trust_env=False) as client:
            deadline = time.perf_counter() + 12
            ready = False
            while time.perf_counter() < deadline:
                require(process.poll() is None, 'Local API process exited during startup')
                try:
                    response = client.get('/health')
                    ready = response.status_code == 200 and response.json().get('service') == 'databridge'
                except httpx.TransportError:
                    pass
                if ready:
                    break
                time.sleep(0.1)
            require(ready, 'Local API did not become ready')
            print('PASS server startup and health check')
            evidence['responses']['health'] = response.json()
            plan = json.loads((ROOT / 'examples' / 'query_september.json').read_text(encoding='utf-8'))
            plan['group_by'] = []
            expected = {'paid_orders': 8, 'paying_customers': 6, 'paid_amount': 79000,
                        'successful_refund_amount': 20000, 'net_sales': 59000}
            for metric, value in expected.items():
                response = client.post('/v1/query', json=plan | {'metric': metric})
                result = response.json()
                require(response.status_code == 200 and result['data'] == [{metric: value}], f'HTTP metric mismatch: {metric}')
                evidence['responses'][metric] = result
            print('PASS 5 metrics via real HTTP requests')
            response = client.post('/v1/query', json=plan | {'group_by': ['region']})
            regional = response.json()
            require(response.status_code == 200 and regional['data'] == [
                {'region': '华东', 'net_sales': 28000}, {'region': '华南', 'net_sales': 18000},
                {'region': '华北', 'net_sales': 8000}, {'region': '西南', 'net_sales': 5000}], 'Regional HTTP mismatch')
            evidence['responses']['by_region'] = regional
            evidence['display_yuan'] = {row['region']: str(Decimal(row['net_sales']) / regional['display_divisor']) for row in regional['data']}
            print('PASS grouped query and yuan display: ' + json.dumps(evidence['display_yuan'], ensure_ascii=False))
            response = client.get('/v1/query-records/' + regional['query_id'])
            require(response.status_code == 200 and response.json()['response'] == regional, 'HTTP query trace mismatch')
            evidence['trace'] = response.json()
            print('PASS retrieving SQL, parameters, and provenance by query_id')
            for name, changed, expected_status in [
                ('invalid_metric', {'metric': 'not_a_metric'}, 'invalid_plan'),
                ('outside_coverage', {'date_start': '2026-07-01'}, 'insufficient_data'),
            ]:
                response = client.post('/v1/query', json=plan | changed)
                require(response.status_code == 422 and response.json()['status'] == expected_status and response.json()['data'] is None, 'Incorrect HTTP failure response')
                evidence['responses'][name] = response.json()
            print('PASS malformed query and insufficient coverage return clear failures')
            output = ROOT / 'outputs' / 'api_smoke.json'
            output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'Evidence saved: {output}')
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
        print('Local smoke-test server stopped')


if __name__ == '__main__':
    main()
