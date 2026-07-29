import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import cast

from translator_tom import (
    CURIE,
    QEdge,
    QEdgeID,
    QNode,
    QNodeID,
    Query,
    QueryGraph,
    TOMBase
)

from . import trapi
from .config import XCRGConfig as Config # TODO
from .debugging import DebugContext, debug_dump_json
from .reporting import Reporter
from .utilities import path_or_none

@dataclass
class RunContext:
    """
    A RunContext maintains and provides convenient access to state
    for a particular query request through the xCRG runner.

    Attributes:
        query_id  : the unique identifier for this run
        query     : the original query submitted to the runner
        config    : the configuration for this run
        reporter  : the reporter for this run
        debug_ctx : the debugging context for this run

        query_edge : a reference to the single edge in the original query
    """

    query_id  : str
    query     : Query
    config    : Config
    reporter  : Reporter
    debug_ctx : DebugContext | None = None

    query_edge : tuple[QEdgeID, QEdge] = field(init = False)

    def __post_init__(self):
        self._query_edge = trapi.get_single_query_edge(self.query)

    @property
    def query_graph(self) -> QueryGraph:
        return cast(QueryGraph, self.query.message.query_graph)

    @property
    def subject_qid(self) -> QNodeID:
        """The subject reference in the original query."""
        return self.query_edge[1].subject

    @property
    def subject_qnode(self) -> QNode:
        """The subject node in the original query."""
        return self.query_graph.nodes[self.subject_qid]

    @property
    def object_qid(self) -> QNodeID:
        """The object reference in the original query."""
        return self.query_edge[1].object

    @property
    def object_qnode(self) -> QNode:
        """The object node in the original query."""
        return self.query_graph.nodes[self.object_qid]

    @property
    def biolink_version(self):
        return self.config.biolink_version

    @property
    def trapi_schema_version(self):
        return self.config.trapi_schema_version

    @property
    def ngd_db_file(self) -> Path | None:
        return path_or_none(self.config.ngd_db_path)

    @property
    def curie_to_pmids_db_file(self) -> Path | None:
        return path_or_none(self.config.curie_to_pmids_db_path)

    @staticmethod
    def new(
        query_id: str,
        query: Query,
        config: Config,
        reporter: Reporter,
    ) -> "RunContext":

        debug_dir = path_or_none(config.debug_dir)

        debug_ctx: DebugContext | None = None
        if debug_dir and debug_dir.exists():
            debug_ctx = DebugContext.new(debug_dir = debug_dir, query = query, query_id = query_id)
        else:
            reporter.info("debug_dir does not exist; debugger will not be used for this run.")

        return RunContext(
            query_id = query_id,
            query = query,
            config = config,
            reporter = reporter,
            debug_ctx = debug_ctx
        )

    def debug_dump_json(self, label: str, payload: object | TOMBase) -> None:
        if self.debug_ctx:
            try:
                debug_dump_json(self.debug_ctx, label, payload)
            except Exception as e:
                self.reporter.warning(str(e))


    def load_tf_list(self) -> list[CURIE]:
        """Load transcription factors from config or bundled package resources."""
        tf_file = path_or_none(self.config.tf_path)

        # Fallback if the configured file is not valid
        if not tf_file or not tf_file.exists():
            tf_file = resources.files("xcrg.resources").joinpath("transcription_factors.json")

        with tf_file.open(encoding = "utf-8") as f:
            tf_data = json.load(f)

        tf_list = tf_data.get("tf") or []
        if not tf_list:
            raise ValueError("No transcription factors were found in transcription_factors.json.")

        return tf_list
