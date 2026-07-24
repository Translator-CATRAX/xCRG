from dataclasses import dataclass, field
from typing import (
    Callable,
    TypeVar
)

from translator_tom import (
    Analysis,
    EdgeBinding,
    EdgeID,
    NodeBinding,
    PathfinderAnalysis,
    QNodeID,
    Result
)

T = TypeVar("T")

# TODO: Temporary until types are untangled
#  This class is effectively a TRAPI Result + additional custom properties
#  The original code would push + pop these xcrg properties
@dataclass
class XCRGResult:
    # TRAPI Result properties
    node_bindings : dict[QNodeID, list[NodeBinding]]    = field(default_factory = dict)
    analyses      : list[Analysis | PathfinderAnalysis] = field(default_factory = list)
    # Custom xCRG properties
    xcrg_direct_bindings    : list[EdgeBinding] = field(default_factory = list)
    xcrg_direct_binding_ids : set[EdgeID]       = field(default_factory = set)
  # xcrg_support_edges      : list[EdgeBinding] = field(default_factory = list)
    xcrg_support_edge_ids   : set[EdgeID]       = field(default_factory = set)
    xcrg_first_score        : float | None      = None
    xcrg_first_index        : int | None        = None # = len(final_results),

    def to_trapi_result(self):
        return Result(node_bindings = self.node_bindings, analyses = self.analyses)


def partition(items: list[T], predicate: Callable[[T], bool]) -> tuple[list[T], list[T]]:
    """Return a list (first) with items that pass predicate, and a list (second) that fail."""
    passed = list[T]()
    failed = list[T]()

    for item in items:
        if predicate(item):
            passed.append(item)
        else:
            failed.append(item)

    return passed, failed


def require(value: object | None, required_type: type[T]) -> T:
    """If value is the required type then return it; otherwise raise TypeError"""
    if not isinstance(value, required_type):
        raise TypeError(f"Required '{required_type}', but value is '{type(value)}'")
    return value