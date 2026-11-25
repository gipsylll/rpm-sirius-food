"""Optional OpenTelemetry tracing and Sentry integration.

The HTTP trace context is stored with an outbox row so background delivery
can continue the same distributed trace after the request ends.
"""

import os
from contextlib import nullcontext

try:
    from opentelemetry import propagate, trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
except ImportError:
    propagate = trace = None


def setup_tracing(service_name, app=None):
    if trace is not None and os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        provider = TracerProvider(
            resource=Resource.create({"service.name": service_name})
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        if app is not None:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app, excluded_urls=r"/metrics$")
    dsn = os.getenv("SENTRY_DSN")
    if dsn:
        import sentry_sdk

        sentry_sdk.init(dsn=dsn, traces_sample_rate=0.0, send_default_pii=False)


def get_trace_headers():
    headers = {}
    if propagate is not None:
        propagate.inject(headers)
    return headers


def span(name, headers=None):
    if trace is None:
        return nullcontext()
    context = propagate.extract(headers or {}) if headers else None
    return trace.get_tracer("sirius.events").start_as_current_span(
        name, context=context
    )


def set_sentry_correlation(cid):
    if os.getenv("SENTRY_DSN"):
        import sentry_sdk

        sentry_sdk.set_tag("correlation_id", cid)


def annotate_correlation(cid):
    if trace is not None and cid:
        trace.get_current_span().set_attribute("correlation_id", cid)
