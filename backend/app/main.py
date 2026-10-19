import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import admin, auth, student, teacher
from .core import config
from .core.db import SessionLocal
from .core.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from .core.security import APIError
from .services.audit import prune_expired


@asynccontextmanager
async def lifespan(_: FastAPI):
    db = SessionLocal()
    try:
        prune_expired(db)
        db.commit()
    finally:
        db.close()
    yield


# L-01：生产默认关闭 /docs、/redoc、/openapi.json，避免登录前把全部路由与
# 请求模型摊开；APP_ENV=dev 时保留，方便本机调试。
app = FastAPI(
    title="青蓝 QingLan API",
    version="1.0",
    lifespan=lifespan,
    docs_url="/docs" if config.DOCS_ENABLED else None,
    redoc_url="/redoc" if config.DOCS_ENABLED else None,
    openapi_url="/openapi.json" if config.DOCS_ENABLED else None,
)

# M-04：ASGI 层请求体上限（含 chunked 请求）
app.add_middleware(BodySizeLimitMiddleware, max_bytes=config.MAX_REQUEST_BYTES)
app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message},
        headers=exc.headers or None,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"code": "VALIDATION_ERROR", "message": "请求参数校验失败"},
    )


app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(admin.router, prefix="/api", tags=["admin"])
app.include_router(teacher.router, prefix="/api/teacher", tags=["teacher"])
app.include_router(student.router, prefix="/api/student", tags=["student"])

_static_dir = os.environ.get("STATIC_DIR", "")
if _static_dir and os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
