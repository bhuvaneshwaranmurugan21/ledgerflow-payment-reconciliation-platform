.PHONY: install lint typecheck test contracts smoke evidence verify clean

install:
	python -m pip install -e ".[dev]"

lint:
	python -m ruff check src tests scripts lambdas spark_jobs orchestration

typecheck:
	python -m mypy

test:
	python -m pytest

contracts:
	python scripts/validate_architecture_contract.py
	python scripts/validate_claim_registry.py

smoke:
	LEDGERFLOW_TOKEN_KEY=synthetic-local-key-not-for-production-2026 \
		python -m ledgerflow evidence --profile smoke --output artifacts

evidence:
	LEDGERFLOW_TOKEN_KEY=synthetic-local-key-not-for-production-2026 \
		python -m ledgerflow evidence --profile evidence --output evidence/verified-local

verify: lint typecheck test contracts smoke

clean:
	rm -rf artifacts .coverage htmlcov .pytest_cache .ruff_cache

