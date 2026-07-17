from typing import Callable, TypeVar

from translator_tom import Result

T = TypeVar("T")

# TODO: Temporary until types are untangled
class XCRGResult:
    def __init__(self):
    #     super().__init__(node_bindings = node_bindings, analyses = analyses)
        self.node_bindings = {} #= node_bindings
        self.analyses = [] # = analyses
        self.xcrg_direct_bindings = []
        self.xcrg_direct_binding_ids = set()
        self.xcrg_support_edges = []
        self.xcrg_support_edge_ids = set()
        self.xcrg_first_score: float | None = None
        self.xcrg_first_index: int | None = None # = len(final_results),


# TODO: Temporary until types are untangled
class ResultPair:
    def __init__(self, result: Result, xcrg: XCRGResult):
        self.result = result
        self.xcrg = xcrg


def partition(items: list[T], predicate: Callable[[T], bool]) -> tuple[list[T], list[T]]:
    """Return a list (first) with items that pass predicate, and a list (second) that fail."""
    passed = list[T]()
    failed = list[T]()

    for item in items:
        if predicate(item):
            passed.append(item)
        else:
            passed.append(item)

    return passed, failed


def require(value: object | None, required_type: type[T]) -> T:
    """If value is the required type then return it; otherwise raise TypeError"""
    if not isinstance(value, required_type):
        raise TypeError(f"Required '{required_type}', but value is '{type(value)}'")
    return value