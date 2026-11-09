"""Optional application-owned OTel setup. Never changes the global provider."""

from typing import Any


def create_otlp_provider(
    endpoint: str, token: str, service_name: str = "swarmcircuit-example"
) -> Any:
    """Install `swarmcircuit-sdk[otel]`; caller owns flushing and shutdown."""
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=endpoint.rstrip("/") + "/v1/traces",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
        )
    )
    return provider
