from copy import deepcopy
from pathlib import Path
from typing import cast

import httpx

from translator_tom import (
    Analysis,
    AuxiliaryGraphsDict,
    Edge,
    EdgeID,
    KnowledgeGraph,
    Query,
    QNodeID,
    QueryGraph,
    Response,
    Result,
)

from . import trapi
from .constants import (
    DIRECT_QEDGE_ID,
    TF_QNODE_ID,
    TP53_CURIE
)
from .context import RunContext
from .utilities import format_json_for_log, make_stable_id


def _result_has_edge_predicate(
    result: Result,
    edges: dict[EdgeID, Edge],
    predicate: str
) -> bool:
    """Return True when any bound knowledge graph edge has the given predicate."""
    for analysis in result.analyses:
        if not isinstance(analysis, Analysis):
            continue
        for bindings in analysis.edge_bindings.values():
            for binding in bindings or []:
                edge = edges.get(binding.id)
                if not edge:
                    continue
                if edge.predicate == predicate:
                    return True
    return False


def _result_preserves_direct_direction(
    result: Result,
    edges: dict[EdgeID, Edge],
    subject_qid: QNodeID,
    object_qid: QNodeID,
) -> bool:
    """Check that a direct result preserves the original source->target direction."""
    source_id = trapi.get_bound_node_curie(result, subject_qid)
    target_id = trapi.get_bound_node_curie(result, object_qid)
    if not source_id or not target_id:
        return False

    for analysis in result.analyses:
        if not isinstance(analysis, Analysis):
            continue
        edge_bindings = analysis.edge_bindings or {}
        direct_bindings = edge_bindings.get(DIRECT_QEDGE_ID) or []
        if not direct_bindings:
            return False

        for binding in direct_bindings:
            edge = edges.get(binding.id)
            if not edge or edge.subject != source_id or edge.object != target_id:
                return False

    return True


def _result_preserves_direction(
    result: Result,
    edges: dict[EdgeID, Edge],
    subject_qid: QNodeID,
    object_qid: QNodeID,
) -> bool:
    """Check that the result preserves source->tf and tf->target edge directions."""
    source_curie = trapi.get_bound_node_curie(result, subject_qid)
    tf_curie = trapi.get_bound_node_curie(result, TF_QNODE_ID)
    target_curie = trapi.get_bound_node_curie(result, object_qid)
    if not source_curie or not tf_curie or not target_curie:
        return False

    for analysis in result.analyses:
        if not isinstance(analysis, Analysis): # TODO
            continue

        e0_bindings = analysis.edge_bindings.get("e0") or []
        e1_bindings = analysis.edge_bindings.get("e1") or []
        if not e0_bindings or not e1_bindings:
            return False

        for binding in e0_bindings:
            edge = edges.get(binding.id)
            if not edge or edge.subject != source_curie or edge.object != tf_curie:
                return False

        for binding in e1_bindings:
            edge = edges.get(binding.id)
            if not edge or edge.subject != tf_curie or edge.object != target_curie:
                return False

    return True


def _filter_direct_response(ctx: RunContext, response: Response) -> Response:
    """Filter subclass and wrong-direction results from a direct Retriever response."""
    message = response.message

    edges: dict[EdgeID, Edge] = {}
    if message.knowledge_graph:
        edges = message.knowledge_graph.edges

    filtered_results: list[Result] = []
    for result in message.results_list:
        if _result_has_edge_predicate(result, edges, "biolink:subclass_of"):
            continue
        if not _result_preserves_direct_direction(result, edges, ctx.subject_qid, ctx.object_qid):
            continue
        filtered_results.append(result)

    filtered_message = deepcopy(message)
    filtered_message.results = filtered_results
    if not filtered_message.knowledge_graph:
        filtered_message.knowledge_graph = KnowledgeGraph.new()
    if not filtered_message.auxiliary_graphs:
        filtered_message.auxiliary_graphs = AuxiliaryGraphsDict()

    # Stamp response with version information if upstream omitted it
    return Response(
        schema_version = response.schema_version or ctx.trapi_schema_version,
        biolink_version = response.biolink_version or ctx.config.biolink_version,
        message = filtered_message,
    )


def _filter_inferred_response(ctx: RunContext, response: Response) -> Response:
    """Filter subclass and wrong-direction results from a two-hop Retriever response."""
    message = response.message

    edges = dict[EdgeID, Edge]()
    if message.knowledge_graph:
        edges = message.knowledge_graph.edges

    filtered_results = []
    for result in message.results_list:
        tf_id = trapi.get_bound_node_curie(result, TF_QNODE_ID)
        if tf_id == TP53_CURIE:
            continue
        if _result_has_edge_predicate(result, edges, "biolink:subclass_of"):
            continue
        if not _result_preserves_direction(result, edges, ctx.subject_qid, ctx.object_qid):
            continue
        filtered_results.append(result)

    filtered_message = deepcopy(message)
    filtered_message.results = filtered_results
    if not filtered_message.knowledge_graph:
        filtered_message.knowledge_graph = KnowledgeGraph.new()
    if not filtered_message.auxiliary_graphs:
        filtered_message.auxiliary_graphs = AuxiliaryGraphsDict()

    # Stamp response with version information if upstream omitted it
    return Response(
        schema_version = response.schema_version or ctx.trapi_schema_version,
        biolink_version = response.biolink_version or ctx.config.biolink_version,
        message = filtered_message
    )


async def _get_trapi_response_from_retriever(ctx: RunContext, query: Query) -> tuple[int ,Response]:
    """Make HTTP query to Retriever and return HTTP status code + TRAPI Response"""

    # Try and return a cached TRAPI Response if appropriate debugging options are set
    cache_filename: Path | None = None
    if ctx.use_http_cache:
        cache_filename: Path = Path(make_stable_id("http_response", query) + ".json")
        if text := ctx.read_cache_file(cache_filename):
            ctx.reporter.debug(f"Returning cached HTTP response: {cache_filename}")
            return 200, Response.from_json(text)

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

        # Write HTTP response to cache if appropriate debugging options are set
        if cache_filename:
            ctx.reporter.debug(f"Writing HTTP response to cache file: {cache_filename}")
            ctx.write_cache_file(cache_filename, http_response.text)

        return http_response.status_code, Response.from_dict(http_response.json())


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
    http_status_code, response = await _get_trapi_response_from_retriever(ctx, query)

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
        http_status_code,
        response.status,
        counts.result_count,
        counts.node_count,
        counts.edge_count,
        response.description,
    )

    if response and response.status != "Success":
        ctx.reporter.warning(
            "xCRG Retriever returned non-complete status %s: %s",
            response.status,
            response.description,
        )
    if counts.result_count == 0 or response.status != "Success":
        for entry in response.logs[:5]:
            ctx.reporter.info("xCRG Retriever log [%s] %s", entry.level or "INFO", entry.message)

    # ctx.debug_dump_json("raw_response", response)

    # Filter response to ensure we have results with correct subclasses, directions, etc.
    qgraph = cast(QueryGraph, query.message.query_graph)
    if trapi.is_two_hop_query(qgraph):
        response = _filter_inferred_response(ctx, response)
    else:
        response = _filter_direct_response(ctx, response)

    return response
