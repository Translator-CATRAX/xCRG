from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cached_property
from importlib import resources
from pathlib import Path
from typing import cast

from translator_tom import (
    CURIE,
    KnowledgeType,
    QEdge,
    QEdgeID,
    QNode,
    QNodeID,
    Query,
    QueryGraph,
    TOMBase,
)

from . import trapi
from .config import Config, Debug_Level  # TODO
from .constants import DEFAULT_TF_FILE, TP53_CURIE
from .debugging import Debug_Context
from .models import (
    DIRECTION_TEMPLATES,
    Direction,
    TF_Batch,
    Progress_Key,
    Progress_Tracker
)
from .reporting import Progress_Message, Reporter
from .utilities import path_or_none


@dataclass
class Run_Context:
    """The context maintains and provides access to state for a single query request."""

    query_id: str
    """The unique identifier for this run"""

    query: Query
    """The original query submitted to the runner"""

    config: Config
    """The configuration for this run"""

    reporter: Reporter
    """The reporter for this run"""

    debug_ctx: Debug_Context | None = None
    """The debugging context for this run"""

    # All fields below here are instantiated independently or in __post_init__

    query_edge_id: QEdgeID = field(init = False)
    """A reference to the ID for the single edge in the original query"""

    query_edge: QEdge = field(init = False)
    """A reference to the single edge in the original query"""

    start_time: datetime = field(init = False, default = datetime.now(UTC))
    """The time when the run began"""

    _progress_trackers: dict[str, Progress_Tracker] = field(init = False, default_factory = dict)
    """Various trackers for making progress visible across individual components, steps, etc."""

    def __post_init__(self):
        self.query_edge_id, self.query_edge = trapi.get_single_query_edge(self.query.message.query_graph)
        # We need to plan head before the query run in order to report progress accurately.
        # Prepare all the various progress trackers we will need for the run.
        match self.knowledge_type:
            case "lookup":
                # Currently, lookup queries simply return results from Retriever
                self._progress_trackers[Progress_Key.LOOKUP_QUERY] = Progress_Tracker(self._on_progress_update)
            case "inferred":
                for key in Progress_Key:
                    self._progress_trackers[key] = Progress_Tracker(self._on_progress_update)
                for batch in self.inferred_batches:
                    self._progress_trackers[batch.key] = batch.progress

    @property
    def query_graph(self) -> QueryGraph:
        return cast(QueryGraph, self.query.message.query_graph)

    @property
    def subject_qid(self) -> QNodeID:
        """The subject reference in the original query."""
        return self.query_edge.subject

    @property
    def subject_qnode(self) -> QNode:
        """The subject node in the original query."""
        return self.query_graph.nodes[self.subject_qid]

    @property
    def object_qid(self) -> QNodeID:
        """The object reference in the original query."""
        return self.query_edge.object

    @property
    def object_qnode(self) -> QNode:
        """The object node in the original query."""
        return self.query_graph.nodes[self.object_qid]

    @property
    def knowledge_type(self) -> KnowledgeType:
        return self.query_edge.knowledge_type or "lookup"

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

    @property
    def scoring_method(self) -> str:
        return self.config.scoring_method

    @property
    def resource_id(self) -> str:
        return self.config.resource_id

    @property
    def num_max_results(self) -> int:
        return self.config.max_results

    @property
    def timeout(self) -> int:
        return self.config.timeout

    def use_cache(self) -> bool:
        return self.config.cache_dir is not None

    @staticmethod
    def new(
        query_id: str,
        query: Query,
        config: Config,
        reporter: Reporter,
    ) -> Run_Context:
        """Instantiate a new RunContext."""
        debug_ctx: Debug_Context | None = None
        if debug_dir := path_or_none(config.debug_dir):
            debug_ctx = Debug_Context.new(
                debug_dir = debug_dir,
                debug_level = config.debug_level,
                run_name = config.debug_run_name,
                query = query,
                query_id = query_id,
            )
        else:
            reporter.info("debug_dir does not exist; debugger will not be used for this run.")

        return Run_Context(
            query_id = query_id,
            query = query,
            config = config,
            reporter = reporter,
            debug_ctx = debug_ctx
        )

    def elapsed_time(self) -> timedelta:
        """The amount of time that has progressed in the run."""
        return datetime.now(UTC) - self.start_time

    def _on_progress_update(self):
        max_value = len(self._progress_trackers) * 100.0
        if not max_value: return
        current_value = sum(x.pct_done for x in self._progress_trackers.values())
        pct_done = round(current_value / max_value * 100, 2)
        self.reporter.handle_message(Progress_Message(pct_done))

    def debug_dump_json(
        self,
        label: str,
        payload: object | TOMBase,
        level: Debug_Level = Debug_Level.ALL
    ) -> None:
        if not (debug := self.debug_ctx): return
        try:
            debug.dump_json(label, payload, level)
        except Exception as e:
            self.reporter.warning(str(e))

    @cached_property
    def tf_list(self) -> list[CURIE]:
        """Get transcription factors from config or bundled package resources."""

        def try_loading_config_tf_file() -> list[CURIE] | None:
            if not (tf_file := path_or_none(self.config.tf_path)):
                return None
            if not tf_file.exists():
                self.reporter.warning(f"Transcription factors file does not exist: {tf_file}")
                return None
            try:
                self.reporter.debug(f"Loading transcription factors from file: {tf_file}")
                with tf_file.open(encoding = "utf-8") as f:
                    return json.load(f).get("tf")
            except Exception as e:
                self.reporter.warning(f"Transcription factors failed to load from file \"{tf_file}\": {e}")
            return None

        def try_loading_default_tf_file() -> list[CURIE] | None:
            try:
                tf_file = resources.files("xcrg.resources").joinpath(DEFAULT_TF_FILE)
                self.reporter.debug(f"Loading transcription factors from default file: {DEFAULT_TF_FILE}")
                with tf_file.open(encoding = "utf-8") as f:
                    return json.load(f).get("tf")
            except Exception as e:
                self.reporter.warning(f"Transcription factors failed to load from file \"{DEFAULT_TF_FILE}\": {e}")
            return None

        tf_list = try_loading_config_tf_file()
        if not tf_list:
            tf_list = try_loading_default_tf_file()
        if not tf_list:
            raise ValueError("Transcription factors failed to load.")

        endpoint_ids = set(self.subject_qnode.ids_list) | set(self.object_qnode.ids_list)

        tf_list = [
            tf_id
            for tf_id in tf_list
            if tf_id != TP53_CURIE and tf_id not in endpoint_ids
        ]
        if not tf_list:
            raise ValueError("No transcription factors remain after TP53/target filtering.")

        return tf_list

    @cached_property
    def inferred_batches(self) -> list[TF_Batch]:
        qualifier = trapi.get_qualifier_value(self.query_edge, "biolink:object_direction_qualifier") or ""
        direction = Direction(qualifier.lower())
        templates = DIRECTION_TEMPLATES[direction]

        # TODO: Do this check as part of config validation
        if self.config.tf_batch_size <= 0: raise ValueError("Batch size must be positive.")
        # Split transcription factors into non-empty batches
        chunk_size = self.config.tf_batch_size
        tf_chunks: list[list[str]] = [
            self.tf_list[i:i+chunk_size]
            for i in range(0, len(self.tf_list), chunk_size)
        ]

        batches = list[TF_Batch]()
        for template in templates:
            for index, tf_ids in enumerate(tf_chunks, start = 1):
                batches.append(TF_Batch(
                    template = template,
                    index = index,
                    tf_ids = tf_ids,
                    progress = Progress_Tracker(self._on_progress_update)
                ))

        return batches

    def get_answer_qid(self) -> QNodeID:
        return trapi.get_answer_qid(self.query_graph, self.subject_qid, self.object_qid)

    def get_cache_dir(self) -> Path | None:
        if not (cache_dir := path_or_none(self.config.cache_dir)): return None
        cache_dir.mkdir(exist_ok = True)
        return cache_dir

    def get_progress_tracker(self, key: Progress_Key) -> Progress_Tracker:
        return self._progress_trackers[key]
