import asyncio
import json
import logging
import subprocess
import sys
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from pydantic.json import pydantic_encoder

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MCP JSON-RPC Models
class JSONRPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str
    method: str
    params: Dict[str, Any]

class JSONRPCResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

# FastAPI Request/Response Models
class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Search query")
    max_results: Optional[int] = Field(default=10, ge=1, le=20, description="Maximum number of results")

class SearchResult(BaseModel):
    title: str
    snippet: str
    url: str
    rank: int

class SearchResponse(BaseModel):
    results: List[SearchResult]
    metadata: Dict[str, Any]
    status: str
    error: Optional[str] = None
    error_type: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    mcp_server_running: bool
    error: Optional[str] = None

class MCPClient:
    """MCP Client that communicates with the web search server via subprocess"""
    
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.is_running = False
        self.timeout = 30  # seconds
        
    async def start_server(self) -> None:
        """Start the MCP server as a subprocess"""
        if self.is_running:
            return
            
        try:
            # Start the MCP server subprocess
            self.process = subprocess.Popen(
                [sys.executable, "-m", "server.mcp_server"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
                universal_newlines=True
            )
            
            # Wait a moment for the server to start
            await asyncio.sleep(1)
            
            # Check if process is still running
            if self.process.poll() is None:
                self.is_running = True
                logger.info("MCP server started successfully")
            else:
                stderr_output = self.process.stderr.read() if self.process.stderr else "Unknown error"
                raise RuntimeError(f"MCP server failed to start: {stderr_output}")
                
        except Exception as e:
            logger.error(f"Failed to start MCP server: {str(e)}")
            await self.cleanup()
            raise
    
    async def stop_server(self) -> None:
        """Stop the MCP server subprocess"""
        if self.process and self.is_running:
            try:
                self.process.terminate()
                # Wait for graceful shutdown
                await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, self.process.wait),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning("MCP server did not terminate gracefully, forcing kill")
                self.process.kill()
            except Exception as e:
                logger.error(f"Error stopping MCP server: {str(e)}")
            finally:
                self.is_running = False
                self.process = None
                logger.info("MCP server stopped")
    
    async def cleanup(self) -> None:
        """Clean up resources"""
        await self.stop_server()
    
    async def call_tool(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Call an MCP tool via JSON-RPC"""
        if not self.is_running or not self.process:
            raise RuntimeError("MCP server is not running")
        
        # Create JSON-RPC request
        request = JSONRPCRequest(
            id=str(uuid4()),
            method=method,
            params=params
        )
        
        try:
            # Send request to MCP server
            request_json = request.model_dump_json()
            logger.debug(f"Sending MCP request: {request_json}")
            
            # Write request to stdin
            self.process.stdin.write(request_json + "\n")
            self.process.stdin.flush()
            
            # Read response from stdout with timeout
            response_line = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, self.process.stdout.readline),
                timeout=self.timeout
            )
            
            if not response_line:
                raise RuntimeError("No response received from MCP server")
            
            # Parse JSON-RPC response
            response_data = json.loads(response_line.strip())
            response = JSONRPCResponse(**response_data)
            
            logger.debug(f"Received MCP response: {response_data}")
            
            # Check for JSON-RPC errors
            if response.error:
                error_msg = response.error.get("message", "Unknown MCP error")
                raise RuntimeError(f"MCP error: {error_msg}")
            
            if not response.result:
                raise RuntimeError("No result in MCP response")
            
            return response.result
            
        except asyncio.TimeoutError:
            raise RuntimeError(f"MCP tool call timed out after {self.timeout} seconds")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON response from MCP server: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"Error calling MCP tool: {str(e)}")
    
    async def search(self, query: str, max_results: Optional[int] = None) -> Dict[str, Any]:
        """Perform web search via MCP server"""
        params = {
            "query": query,
            "max_results": max_results or 10
        }
        # Call the tool directly, not via tools/call
        return await self.call_tool("web_search", params)
    
    async def check_health(self) -> bool:
        """Check if MCP server is healthy"""
        if not self.is_running or not self.process:
            return False
        # Only check if process is still running and responsive
        if self.process.poll() is not None:
            self.is_running = False
            return False
        return True

# Global MCP client instance
mcp_client = MCPClient()

# FastAPI app lifecycle
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage FastAPI app lifecycle"""
    # Startup
    try:
        await mcp_client.start_server()
        logger.info("FastAPI client started successfully")
    except Exception as e:
        logger.error(f"Failed to start MCP client: {str(e)}")
        raise
    
    yield
    
    # Shutdown
    await mcp_client.cleanup()
    logger.info("FastAPI client shutdown complete")

# Create FastAPI app
app = FastAPI(
    title="MCP Web Search Client",
    description="FastAPI client for MCP web search server",
    version="1.0.0",
    lifespan=lifespan
)

@app.post("/search", response_model=SearchResponse)
async def search_web(request: SearchRequest) -> SearchResponse:
    """Perform web search via MCP server"""
    try:
        # Call MCP server
        result = await mcp_client.search(request.query, request.max_results)
        
        # Parse results
        if result.get("status") == "success":
            # Convert results to SearchResult objects
            search_results = []
            for item in result.get("results", []):
                search_results.append(SearchResult(
                    title=item["title"],
                    snippet=item["snippet"],
                    url=item["url"],
                    rank=item["rank"]
                ))
            
            return SearchResponse(
                results=search_results,
                metadata=result.get("metadata", {}),
                status="success"
            )
        else:
            # Handle error response
            return SearchResponse(
                results=[],
                metadata={},
                status="error",
                error=result.get("error", "Unknown error"),
                error_type=result.get("error_type", "unknown")
            )
            
    except Exception as e:
        logger.error(f"Search error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )

@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check the health of the MCP server"""
    try:
        is_healthy = await mcp_client.check_health()
        
        if is_healthy:
            return HealthResponse(
                status="healthy",
                mcp_server_running=True
            )
        else:
            return HealthResponse(
                status="unhealthy",
                mcp_server_running=False,
                error="MCP server is not responding"
            )
            
    except Exception as e:
        logger.error(f"Health check error: {str(e)}")
        return HealthResponse(
            status="unhealthy",
            mcp_server_running=False,
            error=str(e)
        )

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "MCP Web Search Client",
        "version": "1.0.0",
        "endpoints": {
            "search": "POST /search",
            "health": "GET /health"
        }
    }

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "client.fastapi_client:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info"
    ) 