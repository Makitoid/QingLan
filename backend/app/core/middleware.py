"""ASGI 层请求体大小限制（M-04）。

Starlette 默认不限制请求体，Pydantic 会先把整段 JSON 物化成字符串再校验，
未认证的大包足以在小内存主机上造成 DoS。这里在路由之前按 Content-Length
和实际读到的字节数双重截断；超限时返回 413 并停止继续读取。
"""
from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse


class BodyTooLarge(Exception):
    pass


class SecurityHeadersMiddleware:
    """L-06 等低危项：给所有响应补上 nosniff，避免浏览器把上传文件猜成可执行类型。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
            await send(message)

        await self.app(scope, receive, with_headers)


class BodySizeLimitMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = None
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    content_length = int(value)
                except ValueError:
                    content_length = None
                break
        if content_length is not None and content_length > self.max_bytes:
            await self._reject(scope, send)
            return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLarge()
            return message

        response_started = False

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLarge:
            if not response_started:
                await self._reject(scope, send)

    @staticmethod
    async def _reject(scope, send):
        response = JSONResponse(
            status_code=413,
            content={"code": "REQUEST_TOO_LARGE", "message": "请求体超过服务器允许的大小"},
        )
        await response(scope, None, send)
