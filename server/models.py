from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any

class WebSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Search query")
    max_results: Optional[int] = Field(default=10, ge=1, le=20, description="Maximum number of results")

class SearchResult(BaseModel):
    title: str
    snippet: str
    url: str = Field(..., description="Valid HTTP/HTTPS URL")
    rank: int
    
    @validator('url')
    def validate_url(cls, v):
        if not v.startswith(('http://', 'https://')):
            raise ValueError('URL must start with http:// or https://')
        return v

class WebSearchResponse(BaseModel):
    results: List[SearchResult]
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata about the search")
    query: str
    total_results: int
    response_time_ms: float 