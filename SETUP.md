# Rapid Reports AI - Complete Setup Guide

This guide provides detailed instructions for setting up Rapid Reports AI from scratch.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Backend Setup](#backend-setup)
3. [Frontend Setup](#frontend-setup)
4. [Database Configuration](#database-configuration)
5. [Environment Variables](#environment-variables)
6. [Running the Application](#running-the-application)
7. [Troubleshooting](#troubleshooting)

## Prerequisites

### Required Software
- **Python 3.11+**: [Download Python](https://www.python.org/downloads/)
- **Node.js 18+**: [Download Node.js](https://nodejs.org/)
- **Poetry** (recommended) or **pip**: [Install Poetry](https://python-poetry.org/docs/#installation)
- **PostgreSQL** (for production) or SQLite (included with Python)

### Required API Keys
1. **Anthropic API Key**: [Get from Anthropic](https://console.anthropic.com/)
2. **Groq API Key**: [Get from Groq](https://console.groq.com/)
3. **Deepgram API Key** (optional): [Get from Deepgram](https://console.deepgram.com/)
4. **SMTP Credentials** (optional): For email functionality

## Backend Setup

### Step 1: Navigate to Backend Directory
```bash
cd backend
```

### Step 2: Install Dependencies

**Using Poetry (Recommended):**
```bash
poetry install
```

**Using pip:**
```bash
pip install -r requirements.txt
```

If `requirements.txt` doesn't exist, install dependencies manually:
```bash
pip install fastapi uvicorn[standard] anthropic google-generativeai python-dotenv pydantic sqlalchemy psycopg2-binary alembic passlib[argon2] python-jose[cryptography] python-multipart aiohttp pydantic-ai groq perplexityai
```

### Step 3: Create Environment File

Create a `.env` file in the `backend` directory:

```bash
touch .env
```

### Step 4: Configure Environment Variables

Open `.env` and add the following:

```env
# ============================================
# REQUIRED API KEYS
# ============================================
ANTHROPIC_API_KEY=your_anthropic_api_key_here
GROQ_API_KEY=your_groq_api_key_here

# ============================================
# OPTIONAL API KEYS
# ============================================
# Deepgram API key for dictation (optional)
DEEPGRAM_API_KEY=your_deepgram_api_key_here

# ============================================
# DATABASE CONFIGURATION
# ============================================
# For local development (SQLite) - leave empty or comment out
# DATABASE_URL=sqlite:///./rapid_reports.db

# For production (PostgreSQL) - uncomment and configure
# DATABASE_URL=postgresql://username:password@localhost:5432/rapid_reports

# ============================================
# EMAIL CONFIGURATION (Optional)
# ============================================
# Resend API (Recommended for production)
# Sign up at https://resend.com and get your API key
RESEND_API_KEY=re_xxxxxxxxxxxxx
# Use your verified domain email (e.g., noreply@yourdomain.com)
# Or use Resend's default: RadFlow <onboarding@resend.dev>
RESEND_FROM_EMAIL=RadFlow <noreply@yourdomain.com>

# SMTP settings (Fallback for development)
# Only needed if Resend is not configured
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password

# Frontend URL for email links
FRONTEND_URL=http://localhost:5173

# ============================================
# SECURITY
# ============================================
# Generate a secret key for JWT tokens
# Run: python -c "import secrets; print(secrets.token_urlsafe(32))"
SECRET_KEY=your_secret_key_here

# JWT token expiration (minutes)
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

### Step 5: Generate Secret Key

Generate a secure secret key for JWT tokens:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output and paste it as `SECRET_KEY` in your `.env` file.

### Step 6: Database Setup

#### Option A: SQLite (Local Development - Default)
No additional setup needed. The database file `rapid_reports.db` will be created automatically in the backend directory on first run.

#### Option B: PostgreSQL (Production)
1. Install PostgreSQL if not already installed
2. Create a database:
```sql
CREATE DATABASE rapid_reports;
```
3. Update `DATABASE_URL` in `.env`:
```env
DATABASE_URL=postgresql://username:password@localhost:5432/rapid_reports
```

### Step 7: Run Database Migrations

The application will create tables automatically on first run. However, if you want to run migrations manually:

```bash
cd backend
alembic upgrade head
```

## Frontend Setup

### Step 1: Navigate to Frontend Directory
```bash
cd frontend
```

### Step 2: Install Dependencies

**Using npm:**
```bash
npm install
```

**Using bun:**
```bash
bun install
```

### Step 3: Configure API URL (if needed)

The frontend is configured to connect to `http://localhost:8000` by default. If your backend runs on a different port, update the API URL in:
- `frontend/src/routes/+page.svelte` (search for `API_URL`)

## Environment Variables Reference

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude | `sk-ant-...` |
| `GROQ_API_KEY` | Groq API key for Qwen/Llama models | `gsk_...` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEEPGRAM_API_KEY` | Deepgram API key for dictation | None |
| `DATABASE_URL` | Database connection string | `sqlite:///./rapid_reports.db` |
| `SMTP_SERVER` | SMTP server for emails | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_USER` | SMTP username | None |
| `SMTP_PASSWORD` | SMTP password/app password | None |
| `FRONTEND_URL` | Frontend URL for email links | `http://localhost:5173` |
| `SECRET_KEY` | JWT secret key | Must be set |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT expiration time | `1440` (24 hours) |

## Running the Application

### Development Mode

#### Terminal 1: Backend
```bash
cd backend
poetry run uvicorn rapid_reports_ai.main:app --reload --host 0.0.0.0 --port 8000
```

Or without Poetry:
```bash
cd backend
uvicorn rapid_reports_ai.main:app --reload --host 0.0.0.0 --port 8000
```

#### Terminal 2: Frontend
```bash
cd frontend
npm run dev
```

### Production Mode

#### Backend
```bash
cd backend
poetry run python -m rapid_reports_ai.main
```

#### Frontend
```bash
cd frontend
npm run build
npm run preview
```

### Access Points

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Documentation (Swagger)**: http://localhost:8000/docs
- **API Documentation (ReDoc)**: http://localhost:8000/redoc

## First-Time Setup Checklist

- [ ] Python 3.11+ installed
- [ ] Node.js 18+ installed
- [ ] Poetry or pip installed
- [ ] Backend dependencies installed
- [ ] Frontend dependencies installed
- [ ] `.env` file created in backend directory
- [ ] `ANTHROPIC_API_KEY` set in `.env`
- [ ] `GROQ_API_KEY` set in `.env`
- [ ] `SECRET_KEY` generated and set in `.env`
- [ ] Database configured (SQLite or PostgreSQL)
- [ ] Backend server running on port 8000
- [ ] Frontend server running on port 5173

## Creating Your First User

1. Navigate to http://localhost:5173
2. Click "Register"
3. Enter your email and password
4. Check your email for verification link (or check console if SMTP not configured)
5. Click verification link
6. Login with your credentials

## Testing the Setup

### Test Backend API
```bash
curl http://localhost:8000/
```

Expected response:
```json
{"message": "Rapid Reports AI API is running"}
```

### Test API Documentation
Open http://localhost:8000/docs in your browser. You should see the Swagger UI.

### Test Frontend
Open http://localhost:5173 in your browser. You should see the login page.

## Troubleshooting

### Backend Issues

#### Port Already in Use
```bash
# Find process using port 8000
lsof -i :8000

# Kill the process
kill -9 <PID>
```

#### Database Connection Error
- **SQLite**: Ensure write permissions in backend directory
- **PostgreSQL**: Verify database exists and credentials are correct

#### Import Errors
```bash
# Ensure you're in the backend directory
cd backend

# Reinstall dependencies
poetry install
# or
pip install -r requirements.txt
```

#### API Key Errors
- Verify API keys are correctly set in `.env`
- Ensure no extra spaces or quotes around values
- Check API key is active and has credits

### Frontend Issues

#### Port Already in Use
```bash
# Find process using port 5173
lsof -i :5173

# Kill the process
kill -9 <PID>
```

#### CORS Errors
- Ensure backend CORS middleware allows `http://localhost:5173`
- Check backend is running on port 8000

#### Build Errors
```bash
# Clear node_modules and reinstall
rm -rf node_modules
npm install
```

### Email Issues

#### Emails Not Sending
- If SMTP not configured, check console for magic links
- For Gmail, use App Password (not regular password)
- Verify SMTP credentials are correct

#### Email Verification Not Working
- Check `FRONTEND_URL` matches your frontend URL
- Verify token hasn't expired (24 hours)
- Check email spam folder

### Database Migration Issues

#### Migration Errors
```bash
cd backend

# Check current migration status
alembic current

# Upgrade to latest
alembic upgrade head

# If issues persist, check migration files
ls migrations/versions/
```

## Production Deployment

### Railway Deployment

1. **Connect Repository**
   - Link your GitHub repository to Railway

2. **Add PostgreSQL Service**
   - Add PostgreSQL database service
   - Railway will provide `DATABASE_URL` automatically

3. **Configure Environment Variables**
   - `ANTHROPIC_API_KEY`
   - `GROQ_API_KEY`
   - `DEEPGRAM_API_KEY` (optional)
   - `SECRET_KEY`
   - `FRONTEND_URL` (your production frontend URL)
   - `SMTP_*` variables (if using email)

4. **Deploy Backend**
   - Railway will detect Python project
   - Set start command: `python -m rapid_reports_ai.main`

5. **Deploy Frontend**
   - Add Node.js service
   - Set build command: `npm run build`
   - Set start command: `npm run preview`

### Environment Variables for Production

Ensure all required variables are set:
- `ANTHROPIC_API_KEY` ✅
- `GROQ_API_KEY` ✅
- `DATABASE_URL` (provided by Railway) ✅
- `SECRET_KEY` ✅
- `FRONTEND_URL` ✅
- `SMTP_*` (optional)

## Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SvelteKit Documentation](https://kit.svelte.dev/)
- [Anthropic API Documentation](https://docs.anthropic.com/)
- [Groq API Documentation](https://console.groq.com/docs)
- [Deepgram API Documentation](https://developers.deepgram.com/)

## Getting Help

If you encounter issues:
1. Check the troubleshooting section above
2. Review error messages in console/logs
3. Check API documentation at `/docs`
4. Open an issue on GitHub

