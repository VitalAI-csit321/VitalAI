from pydantic import BaseModel, Field


class PageParams(BaseModel):
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
