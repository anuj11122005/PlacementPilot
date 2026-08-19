# PlacementPilot — Deployment Setup Guide

> **Platform stack:** Supabase (database) · Google Cloud Run (backend) · Vercel (frontend)
>
> See [DECISIONS.md D10](file:///c:/Users/anujr/OneDrive/Desktop/PlacementPilot/DECISIONS.md) for why this stack was chosen.

---

## Prerequisites

| Tool | Install | Verify |
|------|---------|--------|
| Google Cloud CLI (`gcloud`) | [Install guide](https://cloud.google.com/sdk/docs/install) | `gcloud --version` |
| Docker Desktop | [Install guide](https://docs.docker.com/desktop/) | `docker --version` |
| Node.js ≥ 18 + npm | [Install guide](https://nodejs.org/) | `node -v && npm -v` |
| Vercel CLI (optional) | `npm i -g vercel` | `vercel --version` |
| `psql` (Postgres client) | Included with Postgres or standalone | `psql --version` |

---

## Part A: Supabase (Database)

### A1. Create the project

1. Go to [supabase.com](https://supabase.com) → **New Project**
2. Choose a name (e.g. `placementpilot`), set a **database password**, pick a region close to your Cloud Run region (recommended: `us-central1` / `South Asia (Mumbai)`)
3. Wait ~2 minutes for provisioning

### A2. Enable pgvector

Supabase ships pgvector in every project — the binary is pre-installed. You just need to activate the extension.

**Option 1 — Supabase Dashboard (easiest):**
1. Go to **Database** → **Extensions** in the left sidebar
2. Search for `vector`
3. Click **Enable**

**Option 2 — SQL Editor:**
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

**Option 3 — psql from your terminal:**
```bash
psql "postgresql://postgres.[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres" \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### A3. Get the connection string

1. Go to **Settings** → **Database** → **Connection string** → **URI** tab
2. Copy the **direct connection** string (not the pooled one — SQLAlchemy manages its own pool):
   ```
   postgresql://postgres.[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:5432/postgres
   ```
3. Alternatively, use the **Session mode** pooler string (port `5432`) if you run into connection limits on the free tier

> [!IMPORTANT]
> Our codebase reads `DATABASE_URL` from the environment. Supabase's connection string format is standard `postgresql://...` — it works with SQLAlchemy and Alembic with zero code changes.

### A4. Run migrations

From your local machine, point Alembic at the Supabase DB:

```bash
# Set the env var temporarily for the migration run
$env:DATABASE_URL = "postgresql://postgres.[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:5432/postgres"

cd backend
alembic upgrade head
```

This applies the existing migration in [`66b974b380d4_init_schema.py`](file:///c:/Users/anujr/OneDrive/Desktop/PlacementPilot/backend/alembic/versions/66b974b380d4_init_schema.py) which creates the `analyses`, `resume_chunks`, and `jd_chunks` tables.

Verify:
```bash
psql "$env:DATABASE_URL" -c "\dt"
```
You should see the three tables plus `alembic_version`.

---

## Part B: Google Cloud Run (Backend)

### B1. One-time GCP setup

```bash
# Login and create/select project
gcloud auth login
gcloud projects create placementpilot --name="PlacementPilot"
gcloud config set project placementpilot

# Enable required APIs
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com

# Create an Artifact Registry repo for Docker images
gcloud artifacts repositories create placementpilot-repo \
  --repository-format=docker \
  --location=us-central1 \
  --description="PlacementPilot Docker images"
```

### B2. Dockerfile compatibility check

> [!NOTE]
> **The existing [`Dockerfile`](file:///c:/Users/anujr/OneDrive/Desktop/PlacementPilot/backend/Dockerfile) needs one small change for Cloud Run.**
>
> The current `CMD` hardcodes port 8000:
> ```dockerfile
> CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
> ```
>
> Cloud Run injects a dynamic `$PORT` env var (usually 8080). The fix is to use a shell-form CMD that reads `$PORT`:
> ```dockerfile
> CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
> ```
>
> This falls back to 8000 for local dev and honors Cloud Run's `$PORT` in production. **Apply this change before building.**

Everything else in the Dockerfile (python:3.11-slim base, gcc/libpq-dev, pip install, SentenceTransformers model bake-in) is Cloud Run compatible.

### B3. Build and push the Docker image

```bash
cd c:\Users\anujr\OneDrive\Desktop\PlacementPilot

# Configure Docker to push to Artifact Registry
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build the image (from project root, using backend/Dockerfile)
docker build -t us-central1-docker.pkg.dev/placementpilot/placementpilot-repo/backend:latest -f backend/Dockerfile backend/

# Push to Artifact Registry
docker push us-central1-docker.pkg.dev/placementpilot/placementpilot-repo/backend:latest
```

### B4. Deploy to Cloud Run

```bash
gcloud run deploy placementpilot-backend \
  --image=us-central1-docker.pkg.dev/placementpilot/placementpilot-repo/backend:latest \
  --region=us-central1 \
  --platform=managed \
  --allow-unauthenticated \
  --memory=2Gi \
  --cpu=1 \
  --timeout=60 \
  --set-env-vars="DATABASE_URL=postgresql://postgres.[REF]:[PASS]@aws-0-[REGION].pooler.supabase.com:5432/postgres,GROQ_API_KEY=your-groq-key,PYTHONPATH=/app"
```

> [!WARNING]
> **Do NOT include `EVAL_MODE` in the env vars.** It defaults to `false` in [`main.py` line 139](file:///c:/Users/anujr/OneDrive/Desktop/PlacementPilot/backend/main.py#L139) when unset. This is the production-safe default.

The deploy command outputs the service URL:
```
Service URL: https://placementpilot-backend-XXXXXXXX-uc.a.run.app
```

Save this — you'll need it for the frontend and eval.

### B5. Verify the deployment

```bash
# Health check
curl https://placementpilot-backend-XXXXXXXX-uc.a.run.app/health

# Confirm eval bypass is BLOCKED (EVAL_MODE is unset)
curl -X POST https://placementpilot-backend-XXXXXXXX-uc.a.run.app/analyze \
  -F "resume=@test_resume.docx" \
  -F "jd_text=short" \
  -H "x-eval-bypass: true"
# Expected: 400 error — bypass not active ✓
```

### B6. Memory note

The SentenceTransformers model (`all-MiniLM-L6-v2`) is baked into the Docker image (~90MB). At runtime it loads into memory. The `--memory=2Gi` flag provides ample headroom. If you see OOM errors on the free tier, try `--memory=1Gi` first — the model itself only needs ~256MB.

---

## Part C: Vercel (Frontend)

### C1. Connect the repo

1. Go to [vercel.com](https://vercel.com) → **Add New Project**
2. **Import** your `PlacementPilot` GitHub repo
3. Configure the project:
   - **Framework Preset:** Vite
   - **Root Directory:** `frontend`
   - **Build Command:** `npm run build` (auto-detected)
   - **Output Directory:** `dist` (auto-detected)

### C2. Set the API URL environment variable

In **Settings** → **Environment Variables**, add:

| Name | Value | Environments |
|------|-------|-------------|
| `VITE_API_URL` | `https://placementpilot-backend-XXXXXXXX-uc.a.run.app` | Production, Preview |

This is read by [`App.tsx` line 38](file:///c:/Users/anujr/OneDrive/Desktop/PlacementPilot/frontend/src/App.tsx#L38):
```typescript
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
```

### C3. Deploy

Click **Deploy**. Vercel builds the Vite app and serves it on a `.vercel.app` domain.

### C4. CORS

The backend's CORS middleware in [`main.py`](file:///c:/Users/anujr/OneDrive/Desktop/PlacementPilot/backend/main.py#L63-L69) currently allows `"*"` origins, so the Vercel frontend can call the Cloud Run backend immediately. For production hardening, you should lock this down to your Vercel domain:

```python
allow_origins=["https://your-project.vercel.app"],
```

---

## Part D: EVAL_MODE Toggle Sequence (Cloud Run)

Same principle as before — temporarily enable, run eval, immediately disable.

### D1. Enable EVAL_MODE

```bash
gcloud run services update placementpilot-backend \
  --region=us-central1 \
  --update-env-vars="EVAL_MODE=true"
```

Wait for the new revision to become active (~30–60s):
```bash
gcloud run services describe placementpilot-backend \
  --region=us-central1 \
  --format="value(status.url)"
```

### D2. Run the eval

```bash
python backend/scripts/run_eval.py \
  --url https://placementpilot-backend-XXXXXXXX-uc.a.run.app/analyze
```

Expected results (per DECISIONS.md D8 baseline):
- 21/21 cases passed
- 12/12 mismatches correctly refused
- 3 verifier interventions

### D3. IMMEDIATELY disable EVAL_MODE

```bash
gcloud run services update placementpilot-backend \
  --region=us-central1 \
  --remove-env-vars="EVAL_MODE"
```

### D4. Verify bypass is dead

```bash
curl -X POST https://placementpilot-backend-XXXXXXXX-uc.a.run.app/analyze \
  -F "resume=@test_resume.docx" \
  -F "jd_text=short" \
  -H "x-eval-bypass: true"
# Expected: 400 error (min_chars=50 enforced) — bypass is dead ✓
```

> [!CAUTION]
> Never leave `EVAL_MODE=true` on the production revision. The toggle window should be < 5 minutes total. Cloud Run's `--remove-env-vars` is cleaner than setting it to `false` — it fully removes the variable.

---

## Environment Variables Summary

### Cloud Run (Backend)

| Variable | Value | Notes |
|----------|-------|-------|
| `DATABASE_URL` | Supabase direct connection string | `postgresql://postgres.[REF]:[PASS]@...` |
| `GROQ_API_KEY` | Your Groq API key | Required for LLM generation + verification |
| `PYTHONPATH` | `/app` | Required for module imports |
| `EVAL_MODE` | **Do NOT set** | Defaults to `false`; only toggle temporarily for eval runs |
| `PORT` | Auto-injected by Cloud Run | Do not set manually |

### Vercel (Frontend)

| Variable | Value | Notes |
|----------|-------|-------|
| `VITE_API_URL` | Cloud Run service URL | e.g. `https://placementpilot-backend-XXXX-uc.a.run.app` |

---

## Required Code Change Before Deploy

### Dockerfile CMD fix for Cloud Run's `$PORT`

**File:** [`backend/Dockerfile`](file:///c:/Users/anujr/OneDrive/Desktop/PlacementPilot/backend/Dockerfile)

```diff
-CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
+CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

This is the **only** code change needed. Everything else (SQLAlchemy `DATABASE_URL` reading, Alembic config, `VITE_API_URL` in the frontend) already works with the new stack.
