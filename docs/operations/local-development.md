# Local development

Requirements: Python 3.13, Xcode 16+, and a Supabase project for integration work.

```bash
cp backend/.env.example backend/.env
python -m pip install -r backend/requirements-dev.lock
make backend-dev PYTHON=python
make worker PYTHON=python
make outfit-worker PYTHON=python
make taste-profile-worker PYTHON=python
make free-text-taste-worker PYTHON=python
```

The API is at `http://127.0.0.1:8000`; OpenAPI is at `/docs`. Configure the iOS development base URL in the app settings.

```bash
make check PYTHON=python
make api-contract PYTHON=python
python backend/scripts/check_migrations.py
xcodebuild -project "ios/AI Closet.xcodeproj" -scheme "AI Closet" \
  -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build
```

The backend owns taxonomy defaults. If `/api/v1/taxonomy` is unavailable, catalog editing remains unavailable instead of silently using a divergent client catalog.
