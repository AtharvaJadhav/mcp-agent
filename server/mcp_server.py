import asyncio
import json
import logging
from typing import Any, Dict, Optional
from mcp.server.fastmcp import FastMCP, Context
from server.web_search import WebSearchTool, WebSearchError, WebSearchTimeoutError, WebSearchAPIError
from server.models import WebSearchRequest

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MCPServer:
    """MCP Server that exposes web search functionality"""
    
    def __init__(self):
        self.web_search_tool = WebSearchTool()
        self.server = FastMCP("web-search-server")
        self._setup_tools()
    
    def _setup_tools(self):
        """Register MCP tools with the server"""
        
        @self.server.tool(
            name="web_search",
            description="Search the web using Serper API"
        )
        async def web_search(
            query: str,
            max_results: Optional[int] = 10,
            ctx: Context = None
        ) -> Dict[str, Any]:
            """
            Search the web using Serper API
            
            Args:
                query: Search query string (required)
                max_results: Maximum number of results to return (optional, default: 10)
                
            Returns:
                Dictionary containing search results with titles, snippets, URLs, and metadata
            """
            # Log using MCP context if available, otherwise use standard logging
            if ctx:
                ctx.info(f"Web search request received: query='{query}', max_results={max_results}")
            else:
                logger.info(f"Web search request received: query='{query}', max_results={max_results}")
            
            try:
                # Create WebSearchRequest object
                request = WebSearchRequest(query=query, max_results=max_results)
                
                # Perform web search using the correct method
                response = await self.web_search_tool.search(request)
                
                # Format results for MCP response
                formatted_results = []
                for result in response.results:
                    formatted_results.append({
                        "title": result.title,
                        "snippet": result.snippet,
                        "url": result.url,
                        "rank": result.rank
                    })
                
                # Create MCP response
                mcp_response = {
                    "results": formatted_results,
                    "metadata": {
                        "query": response.query,
                        "total_results": response.total_results,
                        "response_time_ms": response.response_time_ms,
                        "api_provider": "serper"
                    },
                    "status": "success"
                }
                
                # Log success using MCP context if available
                success_msg = f"Web search completed successfully: {response.total_results} results, {response.response_time_ms:.2f}ms"
                if ctx:
                    ctx.info(success_msg)
                else:
                    logger.info(success_msg)
                
                return mcp_response
                
            except WebSearchTimeoutError as e:
                logger.error(f"Web search timeout: {str(e)}")
                return {
                    "error": "Search request timed out",
                    "details": str(e),
                    "status": "error",
                    "error_type": "timeout"
                }
                
            except WebSearchAPIError as e:
                logger.error(f"Web search API error: {str(e)}")
                return {
                    "error": "API error occurred",
                    "details": str(e),
                    "status": "error",
                    "error_type": "api_error"
                }
                
            except WebSearchError as e:
                logger.error(f"Web search error: {str(e)}")
                return {
                    "error": "Search error occurred",
                    "details": str(e),
                    "status": "error",
                    "error_type": "search_error"
                }
                
            except Exception as e:
                logger.error(f"Unexpected error during web search: {str(e)}", exc_info=True)
                return {
                    "error": "Unexpected error occurred",
                    "details": "Internal server error",
                    "status": "error",
                    "error_type": "internal_error"
                }
    
    def run(self):
        """Run the MCP server using stdio communication"""
        logger.info("Starting MCP web search server...")
        
        try:
            # Run the FastMCP server via stdio
            self.server.run(transport="stdio")
        except Exception as e:
            logger.error(f"Failed to start MCP server: {str(e)}", exc_info=True)
            raise

def main():
    """Main entry point for the MCP server"""
    server = MCPServer()
    
    try:
        # Run the server
        server.run()
    except KeyboardInterrupt:
        logger.info("MCP server stopped by user")
    except Exception as e:
        logger.error(f"MCP server failed: {str(e)}", exc_info=True)
        exit(1)

if __name__ == "__main__":
    main() 