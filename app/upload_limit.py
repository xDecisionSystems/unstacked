"""Refuse an oversized upload before its body is buffered anywhere.

A length check inside the route handler is already too late.  FastAPI reads
and parses the whole multipart body — spooling every byte past the first
megabyte to a temporary file — before it calls the endpoint, so by the time
application code could measure the upload, the disk cost has been paid.

This is deliberately a raw ASGI middleware rather than a
``BaseHTTPMiddleware`` subclass: only at the ASGI layer can the request's
``receive`` channel be wrapped, which is what makes it possible to stop
consuming a body part-way through instead of measuring it afterwards.  Two
checks apply, because either one alone leaves a hole:

* a declared ``Content-Length`` over the budget is refused outright, and the
  body is never read at all;
* the bytes actually delivered are counted as they arrive, so a request that
  understates its length or omits it entirely (``Transfer-Encoding: chunked``)
  is cut off once it crosses the budget rather than being trusted.

The overrun is reported by raising ``HTTPException`` from inside ``receive``.
That propagates out of the form parser and through FastAPI's body-parsing
guard, which re-raises ``HTTPException`` unchanged, so the client sees a 413
rather than a generic parse failure.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from fastapi import HTTPException, status

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

# Headroom for the multipart envelope — boundaries, part headers, and the
# trailing delimiter — so the budget describes the file the operator
# configured rather than the encoding overhead around it.
MULTIPART_OVERHEAD_BYTES = 8_192

_TOO_LARGE_DETAIL = "Upload exceeds the configured size limit"


class UploadSizeLimitMiddleware:
    """Bound the request body of upload routes without buffering it first."""

    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        max_bytes: int,
        overhead_bytes: int = MULTIPART_OVERHEAD_BYTES,
    ) -> None:
        self.app = app
        self.limit = max_bytes + overhead_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not _is_upload_request(scope):
            await self.app(scope, receive, send)
            return
        declared = _declared_length(scope)
        if declared is not None and declared > self.limit:
            # Return without ever invoking the application, so nothing
            # downstream is given the chance to read the body.
            await _send_too_large(send)
            return
        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    raise HTTPException(
                        status.HTTP_413_CONTENT_TOO_LARGE, _TOO_LARGE_DETAIL
                    )
            return message

        await self.app(scope, counting_receive, send)


def _is_upload_request(scope: Scope) -> bool:
    """Match only the asset-upload routes.

    Scoped rather than global on purpose: a body cap that silently applied to
    every route would be a second, invisible limit competing with the ones
    each route already documents (``max_page_bytes`` and friends).  A blanket
    request ceiling belongs in the reverse proxy in front of the app.
    """

    return (
        scope.get("type") == "http"
        and scope.get("method") == "POST"
        and scope.get("path", "").endswith("/assets")
    )


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name.lower() == b"content-length":
            try:
                return int(value)
            except ValueError:
                # An unparseable length is not evidence of anything; the
                # streaming counter still bounds this request.
                return None
    return None


async def _send_too_large(send: Send) -> None:
    body = json.dumps({"detail": _TOO_LARGE_DETAIL}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status.HTTP_413_CONTENT_TOO_LARGE,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                # The body was refused unread, so tell the client not to reuse
                # a connection whose stream is still mid-request.
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
