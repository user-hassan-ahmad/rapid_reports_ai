# Rapid Reports AI

A comprehensive AI-powered medical report generation platform, specifically designed for radiology reports. Generate, enhance, and manage medical reports using advanced AI models with support for custom templates, real-time dictation, and intelligent report enhancement.

## 🚀 Features

### Core Functionality
- **Auto Report Generation**: Pre-built templates for quick report generation with auto-detected variables
- **Custom Templates**: Create, edit, and manage your own report templates with custom variables and instructions
- **Report Enhancement**: Intelligent enhancement pipeline with:
  - Finding extraction and consolidation
  - Clinical guideline search and synthesis
  - Completeness analysis and suggestions
- **Report Versioning**: Full version history for both templates and reports with restore capabilities
- **Real-time Dictation**: Medical-grade transcription using Deepgram's Nova-3 Medical model
- **Report History**: Complete history of all generated reports with search and filtering
- **User Settings**: Customizable preferences including default model, auto-save, and API key management

### AI Models Supported
- **Claude Sonnet 4** (Anthropic) - Primary report generation
- **Qwen 3 32B** (via Groq) - Fallback and enhancement tasks
- **Llama 3.3 70B** (via Groq) - Guideline synthesis and query generation
- **Deepgram Nova-3 Medical** - Medical dictation/transcription

### User Management
- Secure authentication with email/password
- Email verification system
- Password reset via magic links
- User signatures for dynamic report injection
- Encrypted API key storage (Deepgram)

## 🏗️ Architecture

### Backend
- **Framework**: FastAPI (Python 3.11+)
- **Database**: PostgreSQL (production) or SQLite (development)
- **ORM**: SQLAlchemy with Alembic migrations
- **Authentication**: JWT tokens with Argon2 password hashing
- **AI Integration**: Pydantic AI for structured outputs, Perplexity for guideline search

### Frontend
- **Framework**: SvelteKit
- **Styling**: TailwindCSS
- **Build Tool**: Vite
- **State Management**: Svelte stores

## 📋 Prerequisites

- **Python**: 3.11 or higher
- **Node.js**: 18+ (for frontend)
- **PostgreSQL**: (for production) or SQLite (for local development)
- **API Keys**:
  - Anthropic API key (required)
  - Groq API key (required for Qwen/Llama models)
  - Deepgram API key (optional, for dictation)
  - SMTP credentials (optional, for email functionality)

## 🛠️ Quick Start

### 1. Clone the Repository
```bash
git clone <repository-url>
cd rapid_reports_ai
```

### 2. Backend Setup

```bash
cd backend

# Install dependencies (using Poetry)
poetry install

# Or using pip
pip install -r requirements.txt

# Create .env file
cp .env.example .env  # If you have an example file
# Or create manually:
touch .env
```

Add to `.env`:
```env
# Required API Keys
ANTHROPIC_API_KEY=your_anthropic_api_key
GROQ_API_KEY=your_groq_api_key

# Optional API Keys
DEEPGRAM_API_KEY=your_deepgram_api_key  # For dictation

# Database (optional - defaults to SQLite for local)
DATABASE_URL=postgresql://user:password@host:port/database

# Email Configuration (optional)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
FRONTEND_URL=http://localhost:5173

# Security
SECRET_KEY=your_secret_key_here  # Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install
# or
bun install
```

### 4. Run the Application

**Backend** (Terminal 1):
```bash
cd backend
poetry run uvicorn rapid_reports_ai.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend** (Terminal 2):
```bash
cd frontend
npm run dev
```

The application will be available at:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Documentation: http://localhost:8000/docs

## 📚 Detailed Setup

For more detailed setup instructions, see [SETUP.md](./SETUP.md).

## 🗄️ Database

### Local Development (SQLite)
The database file `rapid_reports.db` will be created automatically in the backend directory.

### Production (PostgreSQL)
1. Create a PostgreSQL database
2. Set `DATABASE_URL` in your environment
3. Tables will be created automatically on first run

### Migrations
The project uses Alembic for database migrations:

```bash
cd backend

# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## 🔌 API Endpoints

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login with email/password
- `GET /api/auth/me` - Get current user info
- `POST /api/auth/forgot-password` - Request password reset
- `POST /api/auth/reset-password` - Reset password with token
- `POST /api/auth/verify-email` - Verify email address
- `POST /api/auth/resend-verification` - Resend verification email

### Auto Reports
- `GET /api/use-cases` - List available use cases
- `GET /api/prompt-details/{use_case}` - Get prompt details
- `POST /api/chat` - Generate report from use case

### Templates
- `GET /api/templates` - List all templates
- `GET /api/templates/{template_id}` - Get template details
- `POST /api/templates` - Create new template
- `PUT /api/templates/{template_id}` - Update template
- `DELETE /api/templates/{template_id}` - Delete template
- `POST /api/templates/{template_id}/generate` - Generate report from template
- `GET /api/templates/{template_id}/versions` - Get template version history
- `POST /api/templates/{template_id}/versions/{version_id}/restore` - Restore template version
- `POST /api/templates/{template_id}/toggle-pin` - Pin/unpin template
- `GET /api/templates/tags` - Get all tags
- `POST /api/templates/tags/rename` - Rename tag
- `POST /api/templates/tags/delete` - Delete tag

### Reports
- `GET /api/reports` - List user reports
- `GET /api/reports/{report_id}` - Get report details
- `DELETE /api/reports/{report_id}` - Delete report
- `POST /api/reports/{report_id}/enhance` - Enhance report with findings and guidelines
- `GET /api/reports/{report_id}/completeness` - Get completeness analysis
- `POST /api/reports/{report_id}/chat` - Chat with report for improvements
- `POST /api/reports/{report_id}/apply-actions` - Apply enhancement actions
- `GET /api/reports/{report_id}/versions` - Get report version history
- `POST /api/reports/{report_id}/versions/{version_id}/restore` - Restore report version
- `PUT /api/reports/{report_id}/update` - Update report content

### Settings
- `GET /api/settings` - Get user settings
- `POST /api/settings` - Update user settings
- `GET /api/settings/status` - Get API key configuration status

### Dictation
- `WebSocket /api/transcribe` - Real-time transcription
- `POST /api/transcribe/pre-recorded` - Transcribe audio file

For detailed API documentation, visit `/docs` when the backend is running.

## 🔐 Security

- Passwords are hashed using Argon2
- JWT tokens for authentication
- API keys encrypted at rest (Deepgram user keys)
- CORS configured for frontend origins
- Email verification required for account activation

## 🧪 Testing

### Backend Tests
```bash
cd backend
poetry run pytest
```

### Frontend Tests
```bash
cd frontend
npm run test
```

## 🚢 Deployment

### Railway Deployment
1. Connect your repository to Railway
2. Add PostgreSQL database service
3. Set environment variables:
   - `ANTHROPIC_API_KEY`
   - `GROQ_API_KEY`
   - `DEEPGRAM_API_KEY` (optional)
   - `SMTP_*` variables (optional)
   - `SECRET_KEY`
   - `FRONTEND_URL`
4. Railway will automatically provide `DATABASE_URL`

### Environment Variables for Production
Ensure all required environment variables are set:
- `ANTHROPIC_API_KEY` (required)
- `GROQ_API_KEY` (required)
- `DATABASE_URL` (provided by Railway)
- `SECRET_KEY` (required)
- `FRONTEND_URL` (required)

## 📖 Usage Guide

### Creating a Custom Template
1. Navigate to the Templates tab
2. Click "Create New Template"
3. Fill in:
   - Name and description
   - Template content with `{{VARIABLE_NAME}}` placeholders
   - Master prompt instructions
   - Select compatible models
4. Save the template

### Generating a Report
1. **Auto Report**: Select a use case, fill in variables, and generate
2. **Templated Report**: Select a template, fill in variables, and generate

### Enhancing a Report
1. Open a report from history
2. Click "Enhance Report"
3. Review findings and guidelines
4. Apply suggested actions or chat for improvements

### Using Dictation
1. Click the microphone button
2. Grant browser permissions
3. Speak your findings
4. Transcript appears in real-time

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

[Add your license here]

## 🙏 Acknowledgments

- Anthropic for Claude API
- Groq for fast inference
- Deepgram for medical transcription
- FastAPI and SvelteKit communities

## 📞 Support

For issues and questions, please open an issue on GitHub.










