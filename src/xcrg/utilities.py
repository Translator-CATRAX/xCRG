from typing import TypeVar

T = TypeVar("T")

def require(value: object | None, required_type: type[T]) -> T:
    """If value is the required type then return it; otherwise raise TypeError"""
    if not isinstance(value, required_type):
        raise TypeError(f"Required '{required_type}', but value is '{type(value)}'")
    return value