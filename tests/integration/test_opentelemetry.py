"""Smoke test OpenTelemetry"""
import uuid

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

import xcrg
from tests.utilities import find_chemicals_affecting_gene


def test_opentelemetry_is_working(config: xcrg.XCRGConfig):
    exporter = InMemorySpanExporter()

    provider = TracerProvider()
    provider.add_span_processor(
        SimpleSpanProcessor(exporter)
    )

    trace.set_tracer_provider(provider)

    query_id = uuid.uuid4().hex
    assert find_chemicals_affecting_gene(
        config,
        "decreased",
        "NCBIGene:5742", # PTGS1
        query_id = query_id
    )

    spans = exporter.get_finished_spans()
    assert len(spans) == 1

    span = spans[0]
    assert span.name == "run_query"
    assert span.attributes["query_id"] == query_id
