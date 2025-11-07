# Mentions Backend

FastAPI backend for the Mentions application.

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL client (for migrations)

### Setup

1. **Create virtual environment**:
   ```bash
   python3.11 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**:
   ```bash
   # Copy .env.example to .env (if needed)
   # Edit .env with your values
   ```

4. **Run migrations** (if not already done):
   ```bash
   # From project root
   export DB_CONN="postgresql://..."
   ./scripts/run-migrations.sh
   ```

5. **Start development server**:
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

6. **Test health endpoint**:
   ```bash
   curl http://localhost:8000/health
   ```

## Project Structure

- `api/` - API route handlers
- `core/` - Core configuration and utilities
- `graph/` - LangGraph generation pipeline
- `reddit/` - Reddit API integration
- `rag/` - RAG system
- `llm/` - LLM utilities
- `models/` - Pydantic models
- `services/` - Business logic services
- `tasks/` - Background task handlers
- `db/` - Database migrations

## Development

### Running Tests
```bash
pytest
```

### Code Formatting
```bash
black .
ruff check .
```

### Type Checking
```bash
mypy .
```

## API Documentation

Once running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Environment Variables

See `.env.example` for all required variables.
