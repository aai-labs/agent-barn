from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass
class Pagination:
    page: int
    size: int


@dataclass
class PaginatedItems(Generic[T]):
    page: int
    page_size: int
    total: int
    items: list[T]
