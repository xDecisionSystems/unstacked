"""Add browser-facing security headers to every response.

Deliberately a raw ASGI middleware, in the same shape as
``app.upload_limit.UploadSizeLimitMiddleware``, since the only thing needed
here -- appending headers to ``http.response.start`` -- has no reason to pay
for ``BaseHTTPMiddleware``'s response buffering.

Content-Security-Policy is intentionally not set here: several templates
(``admin.html``, ``home_editor.html``, and others) rely on inline
``<script>`` blocks for their interactivity, and a CSP that actually
restricted ``script-src`` would break them outright without a nonce or hash
threaded through every template first. Shipping a CSP with
``'unsafe-inline'`` would look like a control while providing none, so this
is left for that separate, larger change rather than faked here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

# Static headers added to every response, regardless of environment. None of
# these have a compatibility cost: nothing in this app frames itself, reads
# geolocation/microphone/camera, or relies on the referrer being forwarded
# cross-origin.
_STATIC_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"geolocation=(), microphone=(), camera=()"),
)

# A year, matching the usual HSTS preload-eligible minimum, plus subdomains
# since a sibling host (e.g. a future public split) should not be reachable
# over plain HTTP either once this one has been.
_HSTS_VALUE = b"max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware:
    """Append security headers, skipping any a route already set itself."""

    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        hsts: bool,
    ) -> None:
        self.app = app
        # Only ever sent when the deployment claims to be production, the
        # same signal the session cookie's Secure flag already trusts
        # (app.web_auth) -- forcing HTTPS in a plain local/dev/test run would
        # make that instance unreachable over its own http:// origin.
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = list(message.get("headers") or [])
                present = {name.lower() for name, _value in headers}
                for name, value in _STATIC_HEADERS:
                    if name not in present:
                        headers.append((name, value))
                if self.hsts and b"strict-transport-security" not in present:
                    headers.append((b"strict-transport-security", _HSTS_VALUE))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
