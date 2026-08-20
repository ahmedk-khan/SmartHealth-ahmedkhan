from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=20)


class SearchResult(BaseModel):
    service_id: int
    service_name: str
    score: float
    department: str
    specialty: str | None = None
    content: str


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]