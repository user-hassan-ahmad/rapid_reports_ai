# Railway Deployment Guide - Database Migrations

## The Problem

When deploying to Railway with PostgreSQL, migrations weren't being applied because:

1. **URL Format Issue**: Railway provides `DATABASE_URL` starting with `postgres://`, but SQLAlchemy 1.4+ requires `postgresql://`
2. **Path Issues**: The migration scripts need to run from the correct directory
3. **Timing**: Migrations need to run before the application starts

## The Solution

### 1. Environment Variables on Railway

Make sure you have the following environment variable set in your Railway project:

- `DATABASE_URL` - Automatically provided by Railway when you add a PostgreSQL database

**Important**: Do NOT manually set this. Railway provides it automatically when you:
1. Add a PostgreSQL plugin to your project
2. Link the database to your service

### 2. Database Setup on Railway

#### First-time Setup:

1. Go to your Railway project dashboard
2. Click "New" → "Database" → "Add PostgreSQL"
3. Railway will automatically:
   - Create a PostgreSQL database
   - Generate a `DATABASE_URL` environment variable
   - Link it to your service

4. The database will be empty initially, so migrations will run on first deploy

#### Verify Connection:

In your Railway service logs, you should see:
```
Running Alembic Migrations
============================================================
Database: [your-railway-postgres-url]
Upgrading database to head revision...
✓ Migrations completed successfully!
```

### 3. How Migrations Are Applied

**Automatic on Deploy**: 
The `railway.json` file configures the start command to:
1. Run `fix_migration_state.py` - Checks current database state and applies needed migrations
2. Start the FastAPI application

**Manual Migration** (if needed):
You can also run migrations manually on Railway using the Railway CLI:

```bash
# Install Railway CLI
npm i -g @railway/cli

# Login to Railway
railway login

# Link to your project
railway link

# Run migrations manually
railway run python backend/run_migrations.py
```

### 4. Local vs Production Differences

| Environment | Database | Migrations |
|------------|----------|------------|
| **Local** | SQLite (`rapid_reports.db`) | Run manually with `alembic upgrade head` |
| **Railway** | PostgreSQL (from `DATABASE_URL`) | Run automatically on deploy |

### 5. Creating New Migrations

When you need to add new migrations:

```bash
# 1. Make changes to your models in backend/src/rapid_reports_ai/database/models.py

# 2. Create a new migration (locally)
cd backend
poetry run alembic revision --autogenerate -m "description of changes"

# 3. Review the generated migration file in backend/migrations/versions/

# 4. Test the migration locally
poetry run alembic upgrade head

# 5. Commit and push to git
git add backend/migrations/versions/*.py
git commit -m "Add migration: description"
git push

# 6. Railway will automatically apply the migration on next deploy
```

### 6. Troubleshooting

#### Migrations not running on Railway?

**Check the logs:**
```bash
railway logs
```

Look for:
- ✓ "Migrations completed successfully!" - All good!
- ✗ "ERROR: DATABASE_URL not set" - Database not linked
- ✗ "Migration failed" - Check the error message

**Common issues:**

1. **DATABASE_URL not set**
   - Solution: Add PostgreSQL database to your Railway project
   - Verify: `railway variables` should show `DATABASE_URL`

2. **Alembic version conflicts**
   - Solution: Run `fix_migration_state.py` which auto-detects and fixes state
   - Manual: `railway run python backend/fix_migration_state.py`

3. **Migration files not found**
   - Solution: Ensure all migration files in `backend/migrations/versions/` are committed to git
   - Check: `git status` should not show uncommitted migration files

#### Force re-run migrations:

If you need to manually trigger migrations:

```bash
# Via Railway CLI
railway run python backend/run_migrations.py

# Or via Railway dashboard
# Go to: Service → Settings → Deploy → Trigger Deploy
```

#### Check database schema:

```bash
# Connect to Railway PostgreSQL
railway run psql $DATABASE_URL

# List tables
\dt

# Check alembic version
SELECT * FROM alembic_version;

# Exit
\q
```

### 7. Best Practices

1. **Always test migrations locally first** on a SQLite database
2. **Review auto-generated migrations** - Alembic isn't perfect
3. **Never edit applied migrations** - Create new ones instead
4. **Backup before major migrations** - Use Railway's database backups
5. **Use descriptive migration names** - Future you will thank you

### 8. Migration Workflow Example

```bash
# Add new column to User model
# Edit: backend/src/rapid_reports_ai/database/models.py

# Create migration
cd backend
poetry run alembic revision --autogenerate -m "add user phone number"

# Review the generated file
# Edit: backend/migrations/versions/XXXXX_add_user_phone_number.py

# Test locally
poetry run alembic upgrade head

# Check if it worked
poetry run python -c "from rapid_reports_ai.database.models import User; print(User.__table__.columns.keys())"

# Commit and push
git add backend/migrations/versions/*
git commit -m "Add user phone number field"
git push

# Railway automatically deploys and runs migrations
# Check logs: railway logs
```

## Files Changed

The following files have been updated to fix the migration issue:

1. **`backend/src/rapid_reports_ai/database/connection.py`**
   - Added URL format conversion (`postgres://` → `postgresql://`)

2. **`backend/fix_migration_state.py`**
   - Added URL format conversion
   - Added logging for debugging

3. **`railway.json`**
   - Updated start command to ensure correct paths

4. **`backend/run_migrations.py`** (NEW)
   - Simple script for manual migration runs
   - Can be used with Railway CLI

## Next Deploy

Your next deployment to Railway will:
1. ✓ Detect the PostgreSQL database
2. ✓ Convert the URL format correctly
3. ✓ Run all pending migrations
4. ✓ Start the application

Just push your code and Railway will handle the rest!

```bash
git add -A
git commit -m "Fix Railway PostgreSQL migrations"
git push
```

