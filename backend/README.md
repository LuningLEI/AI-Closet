# Backend

FastAPI service for AI Closet.

## Responsibilities

- Authenticated API routes
- Supabase repository access
- Private Storage upload and signed URL generation
- OpenAI Vision recognition
- Embedding generation
- Recognition queue worker
- Weather-aware and preference-aware recommendations

## Run

```bash
cd backend
/opt/anaconda3/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Worker:

```bash
cd backend
/opt/anaconda3/bin/python -m app.worker
```

## Check

```bash
cd backend
/opt/anaconda3/bin/python -m compileall app
```

Run tests:

```bash
cd backend
/opt/anaconda3/bin/python -m pytest
```
