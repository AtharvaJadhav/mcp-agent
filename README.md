# MCP Agent

A production-ready research agent using the Model Context Protocol (MCP), FastAPI, and Serper web search.

## Features
- Async MCP server with web search tool (Serper API)
- FastAPI client for HTTP access
- Full test suite with pytest and Serper API mocking

## Setup
1. **Clone the repo**
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Set your Serper API key:**
   - Create a `.env` file:
     ```
     SERPER_API_KEY=your_real_serper_api_key
     REQUEST_TIMEOUT=30
     MAX_RESULTS=20
     LOG_LEVEL=INFO
     ```

## Usage
- **Start FastAPI client (runs MCP server as subprocess):**
  ```bash
  python -m client.fastapi_client
  ```
- **POST /search** for web search:
  ```json
  { "query": "search term", "max_results": 10 }
  ```
- **GET /health** for health check

## Testing
- **Run all tests:**
  ```bash
  pytest tests/test_e2e.py -v
  ```
- **Run integration test (real Serper API):**
  ```bash
  pytest -m integration tests/test_e2e.py
  ```

---
MIT License 