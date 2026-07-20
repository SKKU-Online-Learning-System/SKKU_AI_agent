from __future__ import annotations

import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MATERIAL_UPLOAD_PATH = re.compile(r"^/api/courses/[^/]+/materials/?$")
REQUEST_TOO_LARGE_DETAIL = "Material upload request body is too large"


class UploadRequestSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_size: int) -> None:
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._is_material_upload(scope):
            await self.app(scope, receive, send)
            return

        content_length = self._content_length(scope)
        if content_length is not None and content_length > self.max_body_size:
            await self._send_too_large(scope, receive, send)
            return

        received_bytes = 0
        body_too_large = False

        async def limited_receive() -> Message:
            nonlocal body_too_large, received_bytes
            if body_too_large:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_size:
                    body_too_large = True
                    return {"type": "http.disconnect"}
            return message

        async def limited_send(message: Message) -> None:
            if not body_too_large:
                await send(message)

        await self.app(scope, limited_receive, limited_send)
        if body_too_large:
            await self._send_too_large(scope, receive, send)

    @staticmethod
    def _is_material_upload(scope: Scope) -> bool:
        return (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and MATERIAL_UPLOAD_PATH.fullmatch(scope.get("path", "")) is not None
        )

    @staticmethod
    def _content_length(scope: Scope) -> int | None:
        for name, value in scope.get("headers", []):
            if name.lower() != b"content-length":
                continue
            try:
                return int(value)
            except ValueError:
                return None
        return None

    @staticmethod
    async def _send_too_large(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            {"detail": REQUEST_TOO_LARGE_DETAIL},
            status_code=413,
        )
        await response(scope, receive, send)
