# Backend Setup Instructions

> **📖 For complete setup instructions covering both backend and frontend, see the main [SETUP.md](../SETUP.md)**

## Quick Setup

### Prerequisites
- Python 3.11 or higher
- Poetry (recommended) or pip
- PostgreSQL (for production) or SQLite (for local development)
- API keys: Anthropic, Groq (required), Deepgram (optional)

### Installation

1. Install dependencies:
```bash
cd backend
poetry install
```

Or with pip:
```bash
pip install -r requirements.txt
```

2. Create `.env` file:
```env
# Required
ANTHROPIC_API_KEY=your_anthropic_api_key
GROQ_API_KEY=your_groq_api_key
SECRET_KEY=your_secret_key_here

# Optional
DEEPGRAM_API_KEY=your_deepgram_api_key
DATABASE_URL=postgresql://user:password@host:port/database

# Email (Resend recommended for production)
RESEND_API_KEY=re_xxxxxxxxxxxxx
RESEND_FROM_EMAIL=RadFlow <noreply@yourdomain.com>
# Or use SMTP fallback:
# SMTP_SERVER=smtp.gmail.com
# SMTP_PORT=587
# SMTP_USER=your_email@gmail.com
# SMTP_PASSWORD=your_app_password
```

3. Run the server:
```bash
poetry run uvicorn rapid_reports_ai.main:app --reload --host 0.0.0.0 --port 8000
```

## Database

- **SQLite (default)**: Created automatically at `./rapid_reports.db`
- **PostgreSQL**: Set `DATABASE_URL` in `.env`

Tables are created automatically on first run. For manual migrations:
```bash
alembic upgrade head
```

## API Documentation

Once running:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

For detailed setup instructions, see the main [SETUP.md](../SETUP.md).

