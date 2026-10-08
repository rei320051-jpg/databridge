"""Local FastAPI entry point; bind to 127.0.0.1 for this development stage."""
import os
import sqlite3
from contextlib import closing
from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from databridge.service import ROOT, QueryError, QueryService, connect_readonly
from databridge.inspection import inspect_csv_files
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
        try:
            with closing(connect_readonly(query_service.database)) as connection:
                metadata = connection.execute('SELECT * FROM dataset_metadata').fetchall()
                if len(metadata) != 1:
                    raise ValueError('invalid metadata')
                tables = ['orders', 'refunds', 'customers']
                counts = {name: connection.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]
                          for name in tables}
            return {'service': 'databridge', 'version': '0.1.0', 'status': 'ok',
                    'database_available': True, **dict(metadata[0]),
                    'tables': tables, 'row_counts': counts}
        except (QueryError, sqlite3.Error, ValueError, OSError):
            return JSONResponse({'service': 'databridge', 'status': 'not_ready',
                                 'database_available': False, 'dataset_version': 'unavailable',
                                 'tables': []}, status_code=503)

    @app.post(API_ENDPOINTS['inspect']['path'])
    async def inspect(files: list[UploadFile] = File(...)):
        """Inspection is read-only: never register or activate the uploaded data."""
        try:
            if len(files) > 3:
                raise HTTPException(422, '最多上传三张 CSV 表，每张业务表一份')
            uploads = []
            for file in files:
                raw = await file.read(20 * 1024 * 1024 + 1)
                if len(raw) > 20 * 1024 * 1024:
                    raise HTTPException(413, '单份 CSV 不得超过 20 MiB')
                uploads.append((file.filename or '', raw))
            return await run_in_threadpool(inspect_csv_files, uploads)
        finally:
            for file in files:
                await file.close()

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


app = create_app(QueryService(database=os.environ.get('DATABRIDGE_DATABASE') or
                              ROOT / 'outputs' / 'demo-v1.1.sqlite3',
                              records=os.environ.get('DATABRIDGE_RECORDS')))
