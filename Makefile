PYTHON ?= /opt/anaconda3/bin/python

.PHONY: backend-dev worker web-dev web-build backend-check backend-test export-openapi web-api-types api-contract check

backend-dev:
	cd backend && $(PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port 8000

worker:
	cd backend && $(PYTHON) -m app.worker

web-dev:
	cd web && npm run dev

web-build:
	cd web && npm run build

backend-check:
	cd backend && $(PYTHON) -m compileall app

backend-test:
	cd backend && $(PYTHON) -m pytest

export-openapi:
	cd backend && $(PYTHON) scripts/export_openapi.py ../docs/api/openapi.json

web-api-types:
	cd web && npm run api:types

api-contract: export-openapi web-api-types

check: backend-check backend-test web-build
