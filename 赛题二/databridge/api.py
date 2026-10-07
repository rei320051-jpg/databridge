"""Local FastAPI entry point; bind to 127.0.0.1 for this development stage."""
import os
from fastapi import Body, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from databridge.service import QueryError, QueryService
from agent.workflow import AgentWorkflow
from shared.contracts import API_ENDPOINTS


def create_app(service=None):
    app = FastAPI(title='DataBridge 查询接口', version='0.1.0')
    query_service = service if service is not None else QueryService()
    workflow = AgentWorkflow(query_service)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        error = QueryError('invalid_plan', 'INVALID_JSON_BODY', '请求必须是合法的JSON对象')
        return JSONResponse(error.response(), status_code=422)

    @app.get('/health')
    def health():
        available = query_service.database.is_file()
        return JSONResponse({'service': 'databridge', 'version': '0.1.0',
                             'status': 'ready' if available else 'not_ready',
                             'database_available': available}, status_code=200 if available else 503)

    @app.post('/v1/query')
    def query(plan: dict = Body(...)):
        result, http_status = query_service.run(plan)
        return JSONResponse(result, status_code=http_status)

    @app.post(API_ENDPOINTS['query']['path'])
    def agent_query(payload: dict = Body(...)):
        """Natural-language gateway; numbers come only from QueryService."""
        return JSONResponse(workflow.run(payload))

    @app.get('/v1/query-records/{query_id}')
    def query_record(query_id: str):
        try:
            return query_service.read_record(query_id)
        except QueryError as error:
            return JSONResponse(error.response(), status_code=error.http_status)

    return app


app = create_app(QueryService(database=os.environ.get('DATABRIDGE_DATABASE'),
                              records=os.environ.get('DATABRIDGE_RECORDS')))
