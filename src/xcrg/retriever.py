from pathlib import Path

import httpx

from translator_tom import (
    AuxiliaryGraphsDict,
    KnowledgeGraph,
    Query,
    Response,
    Result,
)
from . import trapi
from .context import RunContext
from .utilities import format_json_for_log


async def run_sync_lookup(ctx: RunContext, query: Query) -> Response:
    """Run a sync Retriever lookup and return its TRAPI response."""
    ctx.reporter.info("Sending xCRG lookup query to %s", ctx.config.retriever_url)
    ctx.reporter.debug(
        "xCRG Retriever query graph: %s",
        format_json_for_log(query.message.query_graph),
    )

    # TODO: xCRG Retriever parameters: {"tiers": [0], "timeout": 210}
    #  I do not think these parameters are being used like this (at least anymore)
    # reporter.debug(
    #     "xCRG Retriever parameters: %s",
    #     format_json_for_log(query.parameters),
    # )

    # Try and return a cached Response if appropriate debugging options are set
    cache_filename: Path | None = None
    if ctx.use_http_cache:
        cache_filename: Path = Path(trapi.make_stable_id_for_query("http_response", query) + ".json")
        if text := ctx.read_cache_file(cache_filename):
            ctx.reporter.debug(f"Returning cached HTTP response: {cache_filename}")
            return Response.from_json(text)

    # TODO: We need to clarify the correct behavior for timeout
    # TODO: timeout = httpx.Timeout(ctx.timeout - ctx.elapsed_time().seconds)
    timeout = httpx.Timeout(timeout = ctx.timeout)
    async with httpx.AsyncClient(timeout = timeout) as client:
        try:
            http_response = await client.post(ctx.config.retriever_url, json = query.to_dict())
            http_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            ctx.reporter.error(
                "xCRG Retriever HTTP error %s from %s: %s",
                exc.response.status_code,
                ctx.config.retriever_url,
                exc.response.text[:2000],
            )
            raise
        response = Response.from_dict(http_response.json())

    message = response.message
    if not message:
        raise ValueError("Retriever response did not contain a TRAPI message.")

    if not message.knowledge_graph:
        message.knowledge_graph = KnowledgeGraph.new()
    if not message.results:
        message.results = list[Result]()
    if not message.auxiliary_graphs:
        message.auxiliary_graphs = AuxiliaryGraphsDict()

    counts = trapi.get_message_statistics(response)

    ctx.reporter.info(
        "xCRG Retriever response HTTP %s; status=%s; results=%s; nodes=%s; edges=%s; description=%s",
        http_response.status_code,
        response.status,
        counts.result_count,
        counts.node_count,
        counts.edge_count,
        response.description,
    )
    if response and response.status != "Complete":
        ctx.reporter.warning(
            "xCRG Retriever returned non-complete status %s: %s",
            response.status,
            response.description,
        )
    if counts.result_count == 0 or response.status != "Complete":
        for entry in response.logs[:5]:
            ctx.reporter.info("xCRG Retriever log [%s] %s", entry.level or "INFO", entry.message)

    # TODO: Is this really necessary?
    # Stamp response with version information if upstream omitted it
    response.schema_version = response.schema_version or ctx.trapi_schema_version
    response.biolink_version = response.biolink_version or ctx.config.biolink_version

    # Write Response to cache if appropriate debugging options are set
    if cache_filename:
        ctx.reporter.debug(f"Writing HTTP response to cache file: {cache_filename}")
        ctx.write_cache_file(cache_filename, response.to_json(as_str = True))

    return response
