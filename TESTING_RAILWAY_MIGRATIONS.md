# Testing Railway Migrations - Complete Guide

## 🔑 Understanding DATABASE_URL on Railway

### **How It Works (Automatic)**

Railway **automatically** provides the `DATABASE_URL` environment variable:

1. ✅ You add a PostgreSQL database to your Railway project
2. ✅ Railway creates `DATABASE_URL` automatically  
3. ✅ Your code reads it via `os.getenv("DATABASE_URL")`
4. ✅ No manual configuration needed!

### **You DON'T Need To:**
- ❌ Copy/paste the database URL from Railway console
- ❌ Manually set DATABASE_URL in environment variables
- ❌ Add it to your code

### **Railway DOES Need:**
- ✅ A PostgreSQL database added to your project (Railway Dashboard → Add Database → PostgreSQL)
- ✅ The database linked to your service

---

## 🧪 How to Test Migrations Are Working

You want to verify that when you deploy, migrations actually run on Railway's PostgreSQL.

### **Option 1: Check Railway Logs (Easiest)**

After deploying, your logs should show:

```
Running Alembic Migrations
============================================================
Upgrading database to head revision...
✓ Migrations completed successfully!
```

### **Option 2: Use Railway CLI (Recommended for Testing)**

Install Railway CLI once:
```bash
npm i -g @railway/cli
railway login
railway link  # Links to your project
```

Then you can:

**Check current database state:**
```bash
# Run connection test
railway run python backend/test_railway_connection.py

# Connect to PostgreSQL directly
railway run psql $DATABASE_URL

# List all tables
railway run psql $DATABASE_URL -c "\dt"

# Check migration version
railway run psql $DATABASE_URL -c "SELECT * FROM alembic_version;"
```

**Run migrations manually:**
```bash
railway run python backend/run_migrations.py
```

### **Option 3: Interactive Test Script (Drop & Recreate Table)**

I've created a safe testing script for you:

```bash
cd backend
./test_migration_on_railway.sh
```

This will:
1. Show current database state
2. Optionally drop the `writing_style_presets` table
3. Run migrations to recreate it
4. Verify it worked

---

## 🎯 Specific Test: Drop Table & Recreate

Here's exactly how to test by dropping a table:

### **Step 1: Check Railway is Set Up**

```bash
# Install Railway CLI (if not already)
npm i -g @railway/cli

# Login
railway login

# Link to your project
railway link
```

### **Step 2: Check Current State**

```bash
# See what's in your Railway database
railway run python backend/test_railway_connection.py
```

This shows:
- Is DATABASE_URL set?
- What tables exist?
- Current migration version

### **Step 3: Drop the Table (Safe Test)**

```bash
# Drop writing_style_presets table
railway run psql $DATABASE_URL -c "DROP TABLE IF EXISTS writing_style_presets CASCADE;"

# Verify it's gone
railway run psql $DATABASE_URL -c "\dt"
```

### **Step 4: Run Migrations to Recreate**

```bash
# Run migrations manually
railway run python backend/run_migrations.py

# Or trigger a deployment (migrations run automatically)
git commit --allow-empty -m "Test migration"
git push
```

### **Step 5: Verify Table Was Recreated**

```bash
# Check if table exists now
railway run psql $DATABASE_URL -c "SELECT tablename FROM pg_tables WHERE tablename = 'writing_style_presets';"

# Or run full test again
railway run python backend/test_railway_connection.py
```

If you see `writing_style_presets` listed, **migrations are working!** ✅

---

## 📋 Quick Reference Commands

### Check Database Status
```bash
# Local database
cd backend
poetry run python test_migrations.py

# Railway database  
railway run python backend/test_railway_connection.py
```

### Run Migrations
```bash
# Local
cd backend
poetry run alembic upgrade head

# Railway (manual)
railway run python backend/run_migrations.py

# Railway (automatic - on deploy)
git push  # Migrations run in startCommand
```

### Inspect Database
```bash
# Railway - List tables
railway run psql $DATABASE_URL -c "\dt"

# Railway - Check migration version
railway run psql $DATABASE_URL -c "SELECT * FROM alembic_version;"

# Railway - Count rows in a table
railway run psql $DATABASE_URL -c "SELECT COUNT(*) FROM users;"

# Railway - Interactive psql
railway run psql $DATABASE_URL
# Then use: \dt, \d+ tablename, SELECT * FROM table, etc.
```

### Environment Variables
```bash
# See all Railway env vars (including DATABASE_URL)
railway variables

# Run any command with Railway env vars
railway run <your-command>
```

---

## 🔍 Troubleshooting

### "DATABASE_URL not set" locally

**This is normal!** Locally you use SQLite, not PostgreSQL.

To test with Railway's PostgreSQL locally:
```bash
railway run python backend/test_migrations.py
```

### Migrations not running on Railway deployment

Check your Railway logs:
```bash
railway logs
```

Look for:
- ✅ "Migrations completed successfully" - Good!
- ❌ "DATABASE_URL not set" - Database not linked
- ❌ "Migration failed" - Check the error

**Fix:**
1. Ensure PostgreSQL database is added in Railway dashboard
2. Ensure database is linked to your service
3. Check `railway.json` has the migration command in `startCommand`

### Table exists but data is missing after migration

Migrations don't preserve data when recreating tables. For production:
- Always test migrations on a copy first
- Use migration `op.execute()` to migrate data
- Backup before destructive migrations

---

## ✅ Testing Checklist

Before deploying to production:

- [ ] Local migrations work: `poetry run alembic upgrade head`
- [ ] Local test passes: `poetry run python test_migrations.py`
- [ ] Railway CLI installed and linked
- [ ] Railway database state checked: `railway run python backend/test_railway_connection.py`
- [ ] Test table drop/recreate works: `./test_migration_on_railway.sh`
- [ ] Railway logs show migration success after deploy

---

## 🚀 Standard Deployment Flow

Your normal deployment process (after initial setup):

```bash
# 1. Make model changes
# Edit: backend/src/rapid_reports_ai/database/models.py

# 2. Create migration
cd backend
poetry run alembic revision --autogenerate -m "description"

# 3. Test locally
poetry run alembic upgrade head
poetry run python test_migrations.py

# 4. Commit and push
git add migrations/versions/*.py
git commit -m "Add migration: description"
git push

# 5. Railway automatically:
#    - Deploys your code
#    - Runs fix_migration_state.py
#    - Applies migrations
#    - Starts your app

# 6. Verify in logs
railway logs  # Look for "✓ Migrations completed successfully!"
```

That's it! Railway handles the rest automatically.

---

## 💡 Key Takeaways

1. **DATABASE_URL is automatic** - Railway provides it, you don't set it
2. **Local = SQLite, Railway = PostgreSQL** - Both work with same code
3. **Migrations run automatically on deploy** - Via `railway.json` startCommand
4. **Test with Railway CLI** - `railway run` lets you test production database safely
5. **Check logs after deploy** - Confirms migrations ran successfully

Need help? Run the test scripts:
- `poetry run python test_migrations.py` (local)
- `railway run python backend/test_railway_connection.py` (Railway)
- `./test_migration_on_railway.sh` (interactive testing)
