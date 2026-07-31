from dataclasses import dataclass


@dataclass
class Pagination:
    page: int
    size: int


@dataclass
class PaginatedItems[T]:
    page: int
    page_size: int
    total: int
    items: list[T]
