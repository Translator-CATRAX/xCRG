import json
import uuid
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
    Result,
    TOMBase
)


MISSING_SORT_VALUE = float("inf")

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


def chunk_values(values: list[str], chunk_size: int) -> list[list[str]]:
    """Split values into non-empty batches."""
    if chunk_size <= 0:
        raise ValueError("Chunk size must be positive.")
    return [values[i : i + chunk_size] for i in range(0, len(values), chunk_size)]


def make_stable_id(prefix: str, payload: object) -> str:
    """Return a deterministic compact id for generated KG/support entries."""
    key = json.dumps(payload, sort_keys=True)
    suffix = uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:16]
    return f"{prefix}_{suffix}"


def desc_optional(value: float | int | None) -> float:
    """Convert optional descending values into ascending sort components."""
    return -float(value) if value is not None else MISSING_SORT_VALUE


def asc_optional(value: float | int | None) -> float:
    """Convert optional ascending values into sort components."""
    return float(value) if value is not None else MISSING_SORT_VALUE


def format_json_for_log(value: object | TOMBase) -> str:
    """Return compact JSON for diagnostic logs."""
    if isinstance(value, TOMBase):
        data = value.to_dict()
    else:
        data = value
    return json.dumps(data, sort_keys=True, separators=(",", ":"))
