"""This module contains disparate classes and structures used throughout the library."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from translator_tom import (
    CURIE,
    KnowledgeGraph,
    Query,
    Response,
)


class Direction(StrEnum):
    INCREASED = "increased"
    DECREASED = "decreased"


Direction_Template = tuple[Direction, Direction]


# Sign-compatible two-hop templates for desired final direction
DIRECTION_TEMPLATES: dict[Direction, tuple[Direction_Template, Direction_Template]] = {
    Direction.INCREASED: (
        (Direction.INCREASED, Direction.INCREASED),
        (Direction.DECREASED, Direction.DECREASED)
    ),
    Direction.DECREASED: (
        (Direction.INCREASED, Direction.DECREASED),
        (Direction.DECREASED, Direction.INCREASED)
    )
}


class Progress_Key(StrEnum):
    """Keys for looking up progress trackers during the run."""
    LOOKUP_QUERY = "LOOKUP_QUERY"
    RANKING      = "RANKING"
    FINALIZING   = "FINALIZING"


@dataclass
class Progress_Tracker:
    notify_upstream : Callable[[], None]
    max_value       : int = field(default = 100)
    current_value   : int = field(default = 0, init = False)

    @property
    def pct_done(self) -> float:
        if not self.max_value: return 0.0
        return self.current_value / self.max_value

    def increment_and_notify_upstream(self):
        self.current_value += 1
        self.notify_upstream()

    def finish_and_notify_upstream(self):
        self.current_value = self.max_value
        self.notify_upstream()

    @staticmethod
    def make_noop_tracker() -> Progress_Tracker:
        """Returns a new Progress_Tracker that with no upstream listener."""
        return Progress_Tracker(notify_upstream = lambda: None)


@dataclass
class TF_Batch:
    template   : Direction_Template
    index      : int
    tf_ids     : list[CURIE]
    # statistics : Message_Statistics
    progress   : Progress_Tracker

    @property
    def key(self) -> str:
        """A key that uniquely identifies this batch"""
        return f"{self.template[0]}_{self.template[1]}_{self.index}"


@dataclass
class TF_Batch_Summary:
    batch_index : int
    tf_ids      : list[str]
    tf_count    : int
    response    : Message_Statistics


@dataclass
class Message_Statistics:
    result_count : int
    node_count   : int
    edge_count   : int

    @staticmethod
    def zero():
        return Message_Statistics(0, 0, 0)

    @staticmethod
    def get_from(entity: Query | Response) -> Message_Statistics:
        """Return compact counts for a TRAPI response."""
        message = entity.message
        knowledge_graph = message.knowledge_graph or KnowledgeGraph.new()
        return Message_Statistics(
            result_count = len(message.results_list),
            node_count = len(knowledge_graph.nodes),
            edge_count = len(knowledge_graph.edges_dict),
        )


@dataclass
class Template_Summary:
    template : Direction_Template
    batches  : list[TF_Batch_Summary] = field(default_factory = list)


@dataclass
class Debug_Summary:
    query_id        : str
    debug_run_dir   : str
    final_direction : str
    tf_count        : int
    batch_size      : int
    batch_count     : int
    direct_response : Message_Statistics     = field(default_factory = Message_Statistics.zero)
    merged_response : Message_Statistics     = field(default_factory = Message_Statistics.zero)
    templates       : list[Template_Summary] = field(default_factory = list)
