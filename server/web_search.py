import asyncio
import aiohttp
import time
from typing import Optional, Dict, Any, List
from server.models import WebSearchRequest, WebSearchResponse, SearchResult
from server.config import settings
import logging

logger = logging.getLogger(__name__)

class WebSearchError(Exception):
    """Base exception for web search errors"""
    pass

class WebSearchTimeoutError(WebSearchError):
    """Raised when the search request times out"""
    pass

class WebSearchAPIError(WebSearchError):
    """Raised when the API returns an error"""
    pass

class WebSearchTool:
    """Production-ready web search tool using Serper API"""
    
    def __init__(self):
        self.api_key = settings.serper_api_key
        self.timeout = settings.request_timeout
        self.max_results = settings.max_results
        self.base_url = "https://google.serper.dev/search"
        
        if not self.api_key:
            raise ValueError("SERPER_API_KEY is required")
    
    async def search(self, request: WebSearchRequest) -> WebSearchResponse:
        """
        Perform web search using Serper API
        
        Args:
            request: WebSearchRequest object with query and max_results
            
        Returns:
            WebSearchResponse with search results and metadata
            
        Raises:
            WebSearchError: For various search-related errors
        """
        start_time = time.time()
        
        try:
            # Prepare request payload
            payload = {
                "q": request.query,
                "num": min(request.max_results or self.max_results, self.max_results)
            }
            
            headers = {
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json"
            }
            
            # Make API request
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    
                    if response.status == 429:
                        raise WebSearchAPIError("API rate limit exceeded")
                    
                    if response.status != 200:
                        error_text = await response.text()
                        raise WebSearchAPIError(f"API error {response.status}: {error_text}")
                    
                    data = await response.json()
                    
        except asyncio.TimeoutError:
            raise WebSearchTimeoutError(f"Request timed out after {self.timeout} seconds")
        except aiohttp.ClientError as e:
            raise WebSearchError(f"Network error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error during web search: {str(e)}")
            raise WebSearchError(f"Unexpected error: {str(e)}")
        
        # Calculate response time
        response_time_ms = (time.time() - start_time) * 1000
        
        try:
            # Parse and validate results
            results = self._parse_results(data, request.query)
            
            return WebSearchResponse(
                results=results,
                metadata={
                    "api_provider": "serper",
                    "status_code": 200,
                    "request_timeout": self.timeout
                },
                query=request.query,
                total_results=len(results),
                response_time_ms=response_time_ms
            )
            
        except Exception as e:
            logger.error(f"Error parsing API response: {str(e)}")
            raise WebSearchError(f"Failed to parse API response: {str(e)}")
    
    def _parse_results(self, data: Dict[str, Any], query: str) -> List[SearchResult]:
        """
        Parse and validate search results from API response
        
        Args:
            data: Raw API response data
            query: Original search query
            
        Returns:
            List of SearchResult objects
            
        Raises:
            WebSearchError: If results cannot be parsed
        """
        try:
            organic_results = data.get("organic", [])
            
            if not isinstance(organic_results, list):
                raise WebSearchError("Invalid response format: 'organic' field is not a list")
            
            results = []
            for i, result in enumerate(organic_results):
                try:
                    # Extract required fields with fallbacks
                    title = result.get("title", "No title")
                    snippet = result.get("snippet", "No description")
                    url = result.get("link", "")
                    
                    # Validate URL
                    if not url or not url.startswith(("http://", "https://")):
                        logger.warning(f"Skipping result with invalid URL: {url}")
                        continue
                    
                    search_result = SearchResult(
                        title=title,
                        snippet=snippet,
                        url=url,
                        rank=i + 1
                    )
                    results.append(search_result)
                    
                except Exception as e:
                    logger.warning(f"Skipping malformed result at index {i}: {str(e)}")
                    continue
            
            return results
            
        except Exception as e:
            raise WebSearchError(f"Failed to parse search results: {str(e)}")
    
 