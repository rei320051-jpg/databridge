"""HTTP consumer of the shared natural-language query interface."""
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from shared.contracts import API_ENDPOINTS, Status


class HTTPAgentClient:
    def __init__(self, base_url, timeout=20, transport=None):
        url = urlsplit(base_url)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('API 地址必须是无凭证、无查询参数的 HTTP(S) 服务地址')
        self.endpoint = base_url.rstrip('/') + API_ENDPOINTS['query']['path']
        self.timeout = timeout
        self.transport = transport or urllib.request.urlopen

    def run(self, payload):
        request = urllib.request.Request(self.endpoint, json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                         {'Content-Type': 'application/json'}, method='POST')
        try:
            with self.transport(request, timeout=self.timeout) as response:
                result = json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError):
            return self._failed('query_api_unavailable', '取数接口无法连接，请检查 API 地址与服务状态。')
        except (UnicodeError, json.JSONDecodeError):
            return self._failed('query_api_invalid_response', '取数接口返回了无效 JSON。')
        if not isinstance(result, dict) or result.get('status') not in Status.ALL:
            return self._failed('query_api_invalid_response', '取数接口响应不符合状态契约。')
        if result['status'] == Status.SUCCESS:
            required = {'data', 'metric', 'definition', 'unit', 'source_tables', 'dataset_version',
                        'query_id', 'warnings', 'plan', 'group_by', 'truncated', 'generated_sql'}
            if (not required <= result.keys() or not isinstance(result['data'], list)
                    or any(not isinstance(row, dict) for row in result['data'])
                    or not isinstance(result['plan'], dict) or not isinstance(result['warnings'], list)
                    or not isinstance(result['group_by'], list) or not isinstance(result['source_tables'], list)
                    or not result['query_id'] or not result['dataset_version'] or not result['generated_sql']):
                return self._failed('query_api_invalid_response', '成功响应缺少数据或可信查询依据。')
        elif not isinstance(result.get('message'), str):
            return self._failed('query_api_invalid_response', '失败响应缺少可理解的说明。')
        return result

    @staticmethod
    def _failed(reason, message):
        return {'status': Status.EXECUTION_FAILED, 'message': message,
                'reason': reason, 'missing': ['可用且符合契约的取数接口'],
                'suggestion': '检查服务后重试。', 'retryable': True}
