# Finance Bot — Deployment Guide (Railway + Supabase)

## Prerequisites

- GitHub account (repo: `financeai888-creator/finance-bot`)
- Railway account (https://railway.app)
- Supabase account (https://supabase.com)
- Telegram bot token (via @BotFather)
- API keys: Anthropic, OpenAI, Google AI

---

## Step 1: Create Supabase Project

1. Go to https://supabase.com → New Project
2. Choose region closest to your users
3. Save the database password
4. After creation, go to **Settings → Database**:
   - Copy **Connection string (URI)** — it looks like:
     ```
     postgresql://postgres.[ref]:password@aws-0-us-east-1.pooler.supabase.co:6543/postgres
     ```
   - Use **Session mode (port 5432)** for migrations, **Transaction mode (port 6543)** for the app
5. Go to **Settings → API**:
   - Copy `URL` → this is `SUPABASE_URL`
   - Copy `anon public` key → this is `SUPABASE_KEY`
   - Copy `service_role` key → this is `SUPABASE_SERVICE_KEY`
6. Enable **pgvector** extension:
   - Go to **Database → Extensions**
   - Search for `vector` and enable it

---

## Step 2: Create Railway Project

1. Go to https://railway.app → New Project → **Deploy from GitHub Repo**
2. Select `financeai888-creator/finance-bot`
3. Railway will create a service named `finance-bot`

### 2a: Web Service (auto-created)

This is the main service, already created. It:
- Builds from Dockerfile
- Runs migrations + FastAPI on startup
- Health check: `/health`

### 2b: Worker Service

1. In your Railway project → **+ New Service → GitHub Repo** (same repo)
2. Rename it to `worker`
3. Go to **Settings → Deploy → Start Command**:
   - Set: `python -m taskiq worker src.core.tasks.broker:broker`
   - OR add env variable: `RAILWAY_PROCESS_TYPE=worker` (uses entrypoint.sh)
4. **Settings → Deploy → Health Check**: Remove/disable (worker has no HTTP port)

### 2c: Redis Service

1. In your Railway project → **+ New Service → Database → Redis**
2. Railway creates a managed Redis instance
3. Copy the `REDIS_URL` from the Redis service variables

---

## Step 3: Configure Environment Variables

In Railway, click on the **web service** → **Variables** tab.

Add all these variables:

```env
# Telegram
TELEGRAM_BOT_TOKEN=<from @BotFather>
TELEGRAM_WEBHOOK_URL=https://<your-app>.up.railway.app/webhook

# Database (from Supabase Step 1)
DATABASE_URL=postgresql://postgres.[ref]:password@aws-0-region.pooler.supabase.co:5432/postgres
SUPABASE_URL=https://[ref].supabase.co
SUPABASE_KEY=<anon key>
SUPABASE_SERVICE_KEY=<service role key>

# Redis (from Railway Redis service)
REDIS_URL=${{Redis.REDIS_URL}}

# LLM API Keys
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_AI_API_KEY=AIza...

# Langfuse (optional, for observability)
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com

# Mem0 (optional)
MEM0_API_KEY=
MEM0_BASE_URL=

# App Settings
APP_ENV=production
LOG_LEVEL=INFO
RATE_LIMIT_PER_MINUTE=30
```

**Important:** Use Railway's **Shared Variables** or **Reference Variables** (`${{Redis.REDIS_URL}}`) for inter-service connections.

Copy the same variables to the **worker** service (except `TELEGRAM_WEBHOOK_URL`).

---

## Step 4: Register Telegram Bot

1. Open Telegram → @BotFather → `/newbot`
2. Save the token → use as `TELEGRAM_BOT_TOKEN`
3. After Railway deploys, set webhook:
   ```
   TELEGRAM_WEBHOOK_URL=https://<your-app>.up.railway.app/webhook
   ```
   The app sets the webhook automatically on startup.

---

## Step 5: Set Up CI/CD (GitHub Actions)

1. In GitHub repo → **Settings → Secrets and variables → Actions**
2. Add secret: `RAILWAY_TOKEN`
   - Get from Railway: **Account Settings → Tokens → Create Token**
3. Push to `main` branch triggers: lint → test → docker build → deploy

---

## Step 6: First Deploy

1. Push code to GitHub:
   ```bash
   git add -A
   git commit -m "Prepare for Railway deployment"
   git push origin main
   ```
2. Railway auto-deploys from GitHub push
3. Watch build logs in Railway dashboard
4. First deploy runs Alembic migrations (creates all 13 tables + RLS policies + pgvector)

---

## Step 7: Verify

1. Check health endpoint:
   ```
   curl https://<your-app>.up.railway.app/health
   ```
   Expected: `{"status": "ok", "api": "ok", "redis": "ok", "database": "ok"}`

2. Send a message to your Telegram bot — it should trigger onboarding

3. Check Railway logs for any errors

---

## Architecture on Railway

```
Railway Project
├── finance-bot (web)     — FastAPI + webhook + migrations
│   ├── Dockerfile build
│   ├── Port: $PORT (auto)
│   └── Health: /health
├── worker                — Taskiq background tasks
│   ├── Same Dockerfile
│   ├── CMD override: taskiq worker
│   └── No HTTP port
└── Redis                 — Managed Redis
    └── Auto-provisioned

External:
├── Supabase              — PostgreSQL + pgvector + RLS
├── Telegram API          — Webhook → /webhook
├── Anthropic API         — Claude (main LLM)
├── OpenAI API            — GPT + Whisper (STT)
├── Google AI API         — Gemini (summarization)
└── Langfuse              — Observability (optional)
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Build fails on `uv sync` | Ensure `uv.lock` is committed to git |
| `asyncpg` connection error | Check `DATABASE_URL` format — app auto-converts `postgresql://` to `postgresql+asyncpg://` |
| Webhook not receiving | Verify `TELEGRAM_WEBHOOK_URL` matches Railway domain |
| Worker not processing | Check worker service logs, verify `REDIS_URL` shared |
| Health check fails | Database or Redis not connected — check env vars |
| RLS blocking queries | Ensure `set_family_context()` is called before queries |
| pgvector not found | Enable `vector` extension in Supabase dashboard |
