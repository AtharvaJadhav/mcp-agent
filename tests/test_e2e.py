import asyncio
import os
import signal
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from unittest import mock

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import pytest
from fastapi import status

# Paths
CLIENT_MODULE = "client.fastapi_client"
SERVER_MODULE = "server.mcp_server"

# Test config
FASTAPI_HOST = "127.0.0.1"
FASTAPI_PORT = 8081
FASTAPI_URL = f"http://{FASTAPI_HOST}:{FASTAPI_PORT}"

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
def fastapi_server():
    """Start FastAPI client (which starts MCP server) as a subprocess for integration tests."""
    import subprocess
    proc = subprocess.Popen(
        [sys.executable, "-m", CLIENT_MODULE],
        env={**os.environ, "PORT": str(FASTAPI_PORT)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Wait for server to start
    for _ in range(30):
        try:
            r = httpx.get(f"{FASTAPI_URL}/health", timeout=1)
            if r.status_code == 200 and r.json().get("mcp_server_running"):
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        proc.terminate()
        raise RuntimeError("FastAPI server did not start in time")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

@pytest.fixture(autouse=True)
def patch_serper(monkeypatch):
    """Mock Serper API for reliable tests."""
    # Patch aiohttp.ClientSession.post in server.web_search
    import server.web_search
    
    class MockResponse:
        def __init__(self, status=200, json_data=None):
            self.status = status
            self._json = json_data or {
                "organic": [
                    {"title": "Test Result", "snippet": "A snippet", "link": "https://example.com"}
                ]
            }
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass
        async def json(self):
            return self._json
        async def text(self):
            return str(self._json)
    
    class MockSession:
        def __init__(self, *a, **kw):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass
        def post(self, *a, **kw):
            return MockResponse()
    
    monkeypatch.setattr(server.web_search.aiohttp, "ClientSession", MockSession)
    yield

@pytest.mark.asyncio
async def test_mcp_server_tool_call():
    """Test MCP server tool call directly (unit test)."""
    from server.web_search import WebSearchTool
    from server.models import WebSearchRequest
    tool = WebSearchTool()
    req = WebSearchRequest(query="test", max_results=1)
    resp = await tool.search(req)
    assert resp.results
    assert resp.results[0].title == "Test Result"

@pytest.mark.asyncio
async def test_fastapi_client_lifecycle(fastapi_server):
    """Test FastAPI client subprocess management and health endpoint."""
    async with httpx.AsyncClient(base_url=FASTAPI_URL) as client:
        # Health check
        r = await client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert data["mcp_server_running"] is True

@pytest.mark.asyncio
async def test_search_workflow(fastapi_server):
    """Test full search workflow: FastAPI → MCP → Serper (mocked)."""
    async with httpx.AsyncClient(base_url=FASTAPI_URL) as client:
        payload = {"query": "test", "max_results": 1}
        r = await client.post("/search", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert data["results"]
        assert data["results"][0]["title"] == "Test Result"

@pytest.mark.asyncio
async def test_error_handling_invalid_query(fastapi_server):
    """Test error handling for invalid query (empty string)."""
    async with httpx.AsyncClient(base_url=FASTAPI_URL) as client:
        payload = {"query": "", "max_results": 1}
        r = await client.post("/search", json=payload)
        assert r.status_code == 422  # FastAPI validation error

@pytest.mark.asyncio
async def test_error_handling_timeout(monkeypatch, fastapi_server):
    """Test error handling for MCP tool call timeout."""
    import server.web_search
    class SlowMockSession:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): pass
        async def post(self, *a, **kw):
            await asyncio.sleep(35)  # longer than client timeout
            return type("Resp", (), {"status": 200, "json": lambda s: {"organic": []}, "__aenter__": lambda s: s, "__aexit__": lambda s, e, t, b: None})()
    monkeypatch.setattr(server.web_search.aiohttp, "ClientSession", SlowMockSession)
    async with httpx.AsyncClient(base_url=FASTAPI_URL) as client:
        payload = {"query": "test", "max_results": 1}
        r = await client.post("/search", json=payload, timeout=40)
        assert r.status_code == 500
        assert "timed out" in r.text

@pytest.mark.asyncio
async def test_error_handling_malformed_response(monkeypatch, fastapi_server):
    """Test error handling for malformed Serper API response."""
    import server.web_search
    class MalformedMockSession:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): pass
        def post(self, *a, **kw):
            class Resp:
                status = 200
                async def __aenter__(self): return self
                async def __aexit__(self, exc_type, exc, tb): pass
                async def json(self): return {"not_organic": []}
                async def text(self): return "malformed"
            return Resp()
    monkeypatch.setattr(server.web_search.aiohttp, "ClientSession", MalformedMockSession)
    async with httpx.AsyncClient(base_url=FASTAPI_URL) as client:
        payload = {"query": "test", "max_results": 1}
        r = await client.post("/search", json=payload)
        assert r.status_code == 500
        assert "Failed to parse" in r.text

@pytest.mark.asyncio
@pytest.mark.integration
async def test_integration_real_serper(monkeypatch, fastapi_server):
    """Integration test: real Serper API (requires valid API key and internet)."""
    # Remove mocking for this test
    monkeypatch.undo()
    async with httpx.AsyncClient(base_url=FASTAPI_URL) as client:
        payload = {"query": "OpenAI", "max_results": 1}
        r = await client.post("/search", json=payload, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert data["results"] 