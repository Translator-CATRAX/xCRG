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

    # TODO: figure out how the timeout ought to work
    timeout = httpx.Timeout(timeout = 5.0) # TODO: query.timeout or 5.0)
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
            if isinstance(entry, dict):
                ctx.reporter.info(
                    "xCRG Retriever log [%s] %s",
                    entry.get("level", "INFO"),
                    entry.get("message"),
                )
            else:
                ctx.reporter.info("xCRG Retriever log %s", entry)

    return response
