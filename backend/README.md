# Rapid Reports AI - Backend

FastAPI backend for the Rapid Reports AI application.

> **📖 For complete setup instructions, see the main [README.md](../README.md) and [SETUP.md](../SETUP.md)**

## Quick Start

1. Install dependencies:
```bash
cd backend
poetry install
```

2. Create a `.env` file with required API keys:
```env
ANTHROPIC_API_KEY=your_anthropic_api_key_here
GROQ_API_KEY=your_groq_api_key_here
SECRET_KEY=your_secret_key_here
```

3. Run the server:
```bash
poetry run uvicorn rapid_reports_ai.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

## API Documentation

Once running, visit:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

## Features

- **Auto Report Generation**: Pre-built templates for quick report generation
- **Custom Templates**: Create and manage your own report templates
- **Report Enhancement**: AI-powered finding extraction, guideline search, and completeness analysis
- **Report Versioning**: Full version history with restore capabilities
- **Real-time Dictation**: Medical-grade transcription via Deepgram
- **User Authentication**: Secure JWT-based auth with email verification

## API Endpoints Overview

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login
- `GET /api/auth/me` - Get current user
- `POST /api/auth/forgot-password` - Request password reset
- `POST /api/auth/reset-password` - Reset password
- `POST /api/auth/verify-email` - Verify email
- `POST /api/auth/resend-verification` - Resend verification

### Auto Reports
- `GET /api/use-cases` - List use cases
- `GET /api/prompt-details/{use_case}` - Get prompt details
- `POST /api/chat` - Generate report

### Templates
- `GET /api/templates` - List templates
- `POST /api/templates` - Create template
- `PUT /api/templates/{id}` - Update template
- `DELETE /api/templates/{id}` - Delete template
- `POST /api/templates/{id}/generate` - Generate from template
- `GET /api/templates/{id}/versions` - Get version history
- `POST /api/templates/{id}/versions/{version_id}/restore` - Restore version

### Reports
- `GET /api/reports` - List reports
- `GET /api/reports/{id}` - Get report
- `POST /api/reports/{id}/enhance` - Enhance report
- `POST /api/reports/{id}/chat` - Chat with report
- `GET /api/reports/{id}/versions` - Get version history

### Settings
- `GET /api/settings` - Get settings
- `POST /api/settings` - Update settings

### Dictation
- `WebSocket /api/transcribe` - Real-time transcription
- `POST /api/transcribe/pre-recorded` - Transcribe audio file

For detailed API documentation, visit `/docs` when the server is running.

