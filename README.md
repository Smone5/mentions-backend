# Mentions Backend

FastAPI backend for the Mentions Reddit Reply Assistant.

## Setup

1. Create virtual environment:
```bash
python3.11 -m venv venv
source venv/bin/activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Copy environment file:
```bash
cp .env.example .env
# Edit .env with your credentials
```

4. Run server:
```bash
uvicorn main:app --reload --port 8000
```

## API Documentation

Once running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Project Structure

- `api/` - API route handlers
- `core/` - Core configuration and utilities
- `graph/` - LangGraph generation pipeline
- `reddit/` - Reddit API integration
- `rag/` - RAG system
- `llm/` - LLM utilities
- `models/` - Pydantic models
- `services/` - Business logic services
- `tasks/` - Background tasks
- `tests/` - Test suite

