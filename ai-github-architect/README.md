# 🏗️ AI GitHub Repository Architect

An enterprise-grade, autonomous AI agent that analyzes any GitHub repository and produces detailed technical architecture reports covering technology stack, system design, security risks, performance bottlenecks, code quality, design patterns, and prioritized improvement roadmaps.

---

## 🌟 Key Features

- **Autonomous Multi-Agent Architecture**: Built with **LangGraph** using a DAG pipeline with parallel execution for specialized analysis nodes (Architecture, Security, Performance, Code Quality).
- **GitHub MCP Server**: Interacts with repositories through a dedicated **Model Context Protocol (MCP)** server via stdio transport.
- **Model Agnostic**: Abstract LLM Provider interface supporting **Google Gemini 2.0 Flash** (extensible to OpenAI, Claude, or local Ollama).
- **Human-in-the-Loop (HITL)**: Workflow interrupts at the approval node, allowing human engineers to approve, reject, or request revisions.
- **Production Persistence**: Full database persistence with **PostgreSQL 16** (SQLAlchemy + Alembic) and **Redis 7** caching.
- **Observability Ready**: Structured JSON logging (`structlog`) with `analysis_id` propagation and **LangSmith** tracing integration.

---

## 📐 Architecture Overview

```
Client App / API ──▶ FastAPI Router ──▶ Analysis Service ──▶ LangGraph Workflow
                                                                │
                 ┌──────────────────────────────────────────────┴──────────────────────────────┐
                 ▼                                                                             ▼
    [GitHub MCP Server (stdio)]                                                    [Specialized Agents]
                 │                                                                             │
    GitHub REST API + Redis Cache                                                   Gemini 2.0 Flash LLM
```

For the complete architectural design and database schema, see [docs/architecture.md](docs/architecture.md).

---

## 🛠️ Quick Start

### 1. Prerequisites
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or standard `pip`
- Docker & Docker Compose (optional, for containerized run)

### 2. Environment Setup

```bash
git clone https://github.com/your-org/ai-github-architect.git
cd ai-github-architect

# Copy environment template
cp .env.example .env

# Edit .env and configure your keys:
# GEMINI_API_KEY=your_gemini_api_key
# GITHUB_TOKEN=your_github_personal_access_token
```

### 3. Option A: Running with Docker Compose (Recommended)

```bash
docker compose up --build
```
The API will be available at `http://localhost:8000`.

### 4. Option B: Running Locally

```bash
# Create virtual environment & install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest tests/unit/ tests/api/ -v

# Start FastAPI development server
uvicorn app.main:app --reload --port 8000
```

---

## 🚀 API Endpoint Guide

### Start Repository Analysis
```http
POST /api/v1/analyze
Content-Type: application/json

{
  "repository_url": "https://github.com/fastapi/fastapi"
}
```
**Response (202 Accepted):**
```json
{
  "analysis_id": "b66e4de0-a5f8-4425-b2c8-f9d43a95f325",
  "status": "STARTED",
  "repository_name": "fastapi/fastapi",
  "created_at": "2026-08-19T10:26:50.190Z",
  "message": "Analysis started for fastapi/fastapi. Poll GET /api/v1/analyze/b66e4de0-a5f8-4425-b2c8-f9d43a95f325 for status."
}
```

### Check Analysis Status
```http
GET /api/v1/analyze/b66e4de0-a5f8-4425-b2c8-f9d43a95f325
```

### Get Final Report
```http
GET /api/v1/analyze/b66e4de0-a5f8-4425-b2c8-f9d43a95f325/report
```

### Human Approval / Revision Request
```http
POST /api/v1/analyze/b66e4de0-a5f8-4425-b2c8-f9d43a95f325/approve
Content-Type: application/json

{
  "action": "APPROVE"
}
```

---

## 🧪 Testing

```bash
# Run unit and API test suite
pytest tests/unit/ tests/api/ -v
```

---

## 📄 License

MIT License. See `LICENSE` for details.
