from __future__ import annotations

import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Course-material uploads and the files a student attaches to a COURSE AGENT
# question are the two multipart bodies the API accepts; both are bounded here
# before the route reads a byte.
MATERIAL_UPLOAD_PATH = re.compile(r"^/api/courses/[^/]+/materials/?$")
ATTACHMENT_UPLOAD_PATH = re.compile(r"^/api/voice/courses/[^/]+/attachments/?$")
REQUEST_TOO_LARGE_DETAIL = "Material upload request body is too large"


class UploadRequestSizeLimitMiddleware:
    def __init__(
        self, app: ASGIApp, max_body_size: int, attachment_max_body_size: int | None = None
    ) -> None:
        self.app = app
        self.max_body_size = max_body_size
        # A student's PDF (a textbook) may be larger than a course material.
        self.attachment_max_body_size = attachment_max_body_size or max_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = self._limit_for(scope)
        if limit is None:
            await self.app(scope, receive, send)
            return

        content_length = self._content_length(scope)
        if content_length is not None and content_length > limit:
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
                if received_bytes > limit:
                    body_too_large = True
                    return {"type": "http.disconnect"}
            return message

        async def limited_send(message: Message) -> None:
            if not body_too_large:
                await send(message)

        await self.app(scope, limited_receive, limited_send)
        if body_too_large:
            await self._send_too_large(scope, receive, send)

    def _limit_for(self, scope: Scope) -> int | None:
        """The body limit this request gets, or None when it is not an upload."""
        if scope["type"] != "http" or scope.get("method") != "POST":
            return None
        path = scope.get("path", "")
        if MATERIAL_UPLOAD_PATH.fullmatch(path) is not None:
            return self.max_body_size
        if ATTACHMENT_UPLOAD_PATH.fullmatch(path) is not None:
            return self.attachment_max_body_size
        return None

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
