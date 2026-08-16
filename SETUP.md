# Setup — PlacementPilot

## Prerequisites

- Python 3.11+
- Node.js 18+
- Docker (for local Postgres + pgvector)
- An API key for your chosen LLM provider

## 1. Clone & environment

```bash
git clone https://github.com/anuj11122005/PlacementPilot.git
cd PlacementPilot
cp .env.example .env   # fill in your API keys and DB URL
```

Add `.env` to `.gitignore` immediately if it isn't already there — never
commit real API keys.

## 2. Database (pgvector via Docker)

```bash
docker run --name placementpilot-db \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  -d ankane/pgvector

# then enable the extension inside the DB
docker exec -it placementpilot-db psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

## 3. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Backend runs at `http://localhost:8000`.

## 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173` (or as configured).

## 5. Environment variables (`.env.example`)

```
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/placementpilot
LLM_API_KEY=your_key_here
EMBEDDING_MODEL=your_model_name_here
RETRIEVAL_CONFIDENCE_THRESHOLD=0.40
```

## 6. Running the eval set

Before merging any change to retrieval or prompts, run the standard eval
pairs described in `RULES.md §5`:

```bash
python scripts/run_eval.py
```

This checks refusal accuracy and hallucination rate against the fixed
test cases (strong match, partial match, no overlap, malformed resume,
vague JD).
