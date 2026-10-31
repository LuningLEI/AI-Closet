PYTHON ?= /opt/anaconda3/bin/python

.PHONY: backend-dev worker outfit-worker taste-profile-worker free-text-taste-worker \
	backend-check backend-lint backend-typecheck backend-test migrations-check \
	docs-check \
	baseline-eval comparison-eval taste-simulation taste-simulation-custom \
	taste-parameter-search export-openapi api-contract check clean

backend-dev:
	cd backend && $(PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port 8000

worker:
	cd backend && $(PYTHON) -m workers.recognition

backend-check:
	cd backend && $(PYTHON) -m compileall app workers tools

backend-lint:
	cd backend && $(PYTHON) -m ruff check app workers

backend-typecheck:
	cd backend && $(PYTHON) -m mypy --follow-imports=skip app/ai/gateway.py app/core/runtime_snapshot.py app/services/recommendation/application.py app/api/routes/recommendations.py

backend-test:
	cd backend && $(PYTHON) -m pytest

migrations-check:
	cd backend && $(PYTHON) scripts/check_migrations.py

docs-check:
	$(PYTHON) scripts/check_markdown_links.py .

baseline-eval:
	cd backend && $(PYTHON) -m tools.evaluation.baseline_eval --help

comparison-eval:
	cd backend && $(PYTHON) -m tools.evaluation.comparison_eval --help

export-openapi:
	cd backend && $(PYTHON) scripts/export_openapi.py ../docs/api/openapi.json

api-contract: export-openapi

check: backend-check backend-lint backend-typecheck backend-test migrations-check docs-check

outfit-worker:
	cd backend && $(PYTHON) -m workers.outfits

taste-profile-worker:
	cd backend && $(PYTHON) -m workers.taste_profiles

free-text-taste-worker:
	cd backend && $(PYTHON) -m workers.free_text_taste

taste-simulation:
	cd backend && $(PYTHON) -m tools.evaluation.taste_learning_simulation --runs 100 --steps 120 --output ../evaluation/taste/simulation

taste-simulation-custom:
	cd backend && $(PYTHON) -m tools.evaluation.taste_learning_simulation --runs 30 --steps 120 --custom-config ../evaluation/taste/simulation/custom_config.json --output ../evaluation/taste/simulation/custom

taste-parameter-search:
	cd backend && $(PYTHON) -m tools.evaluation.taste_parameter_search

clean:
	rm -rf .pytest_cache backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache ios/build
	find backend scripts -type d -name __pycache__ -prune -exec rm -rf {} +
