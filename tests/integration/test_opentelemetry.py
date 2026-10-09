"""Smoke test OpenTelemetry"""
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from xcrg.config import XCRGConfig
from xcrg.dev import Query_Args, find_chemicals_affecting_gene
from xcrg.models import Direction


def test_opentelemetry_is_working(config: XCRGConfig):
    exporter = InMemorySpanExporter()

    provider = TracerProvider()
    provider.add_span_processor(
        SimpleSpanProcessor(exporter)
    )

    trace.set_tracer_provider(provider)

    args = Query_Args(Direction.DECREASED, "NCBIGene:5742", )  # PTGS1
    assert find_chemicals_affecting_gene(config, args)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1

    span = spans[0]
    assert span.name == "run_query"
    assert (attributes := span.attributes)
    assert attributes["query_id"] == args.query_id
