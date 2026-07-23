"""Shared pagination envelope.

Every list endpoint returns this same shape so the frontend can use one
table/pagination component everywhere instead of special-casing each page.
"""

from pydantic import BaseModel, Field

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


class PageParams(BaseModel):
    """Query params for a paginated list. Used via fastapi.Depends()."""

    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0)


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total
