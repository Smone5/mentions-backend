# Mentions Backend

FastAPI backend service with LangGraph-powered AI workflows for Reddit engagement.

## Features

- **LangGraph Workflows**: Multi-agent AI system for content generation
- **RAG Implementation**: Context-aware response generation
- **Rate Limiting**: Reddit API compliance
- **PostgreSQL**: Structured data storage
- **Redis**: Caching and job queuing
- **Observability**: LangSmith integration for workflow monitoring

## Tech Stack

- **Framework**: FastAPI
- **ORM**: SQLAlchemy
- **Migrations**: Alembic
- **AI**: LangChain, LangGraph
- **Task Queue**: Celery + Redis
- **Authentication**: JWT

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Redis 7+

### Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your configuration

# Run database migrations
alembic upgrade head

# Start development server
uvicorn app.main:app --reload --port 8000
```

## Project Structure

```
mentions_backend/
├── app/
│   ├── main.py              # FastAPI application
│   ├── core/                # Core configuration
│   ├── models/              # SQLAlchemy models
│   ├── schemas/             # Pydantic schemas
│   ├── api/                 # API routes
│   ├── services/            # Business logic
│   └── workflows/           # LangGraph workflows
├── tests/
├── alembic/                 # Database migrations
└── requirements.txt
```

## Environment Variables

See `.env.example` for required configuration:

- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string
- `OPENAI_API_KEY`: OpenAI API key
- `REDDIT_CLIENT_ID`: Reddit API credentials
- `REDDIT_CLIENT_SECRET`: Reddit API credentials
- `JWT_SECRET_KEY`: Secret key for JWT tokens

## Development

```bash
# Run tests
pytest

# Run with auto-reload
uvicorn app.main:app --reload

# Run Celery worker
celery -A app.celery_app worker --loglevel=info
```

## Documentation

API documentation available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## License

Proprietary - All rights reserved

