"""Correlation ID and HTTP metrics for the event-driven demo."""

import json
import logging
import sys
import time
from contextvars import ContextVar
from uuid import uuid4

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

from app.core.tracing import annotate_correlation, set_sentry_correlation

correlation_id = ContextVar("correlation_id", default="")
requests = Counter(
    "sirius_http_requests_total", "HTTP requests", ["method", "path", "status"]
)
latency = Histogram(
    "sirius_http_request_duration_seconds", "HTTP request duration", ["method", "path"]
)
logger = logging.getLogger("sirius")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.propagate = False


def log(event: str, **fields):
    logger.warning(
        json.dumps(
            {"event": event, "correlation_id": correlation_id.get(), **fields},
            ensure_ascii=False,
        )
    )


async def observe(request, call_next):
    incoming = request.headers.get("X-Correlation-ID", "")
    cid = (
        incoming
        if 0 < len(incoming) <= 128 and incoming.isprintable()
        else str(uuid4())
    )
    token = correlation_id.set(cid)
    set_sentry_correlation(cid)
    annotate_correlation(cid)
    start = time.monotonic()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Correlation-ID"] = cid
        return response
    finally:
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        requests.labels(request.method, path, str(status)).inc()
        latency.labels(request.method, path).observe(time.monotonic() - start)
        log("http_request", method=request.method, path=path, status=status)
        correlation_id.reset(token)


def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
