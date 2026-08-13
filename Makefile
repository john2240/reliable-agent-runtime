.PHONY: install run demo adaptive-demo test coverage lint format openapi openapi-check quality acceptance clean

install:
	python -m pip install -e ".[dev]"

run:
	python -m reliable_agent_runtime --reload

demo:
	python examples/run_demo.py

adaptive-demo:
	python examples/adaptive_agent_loop.py

test:
	pytest -q

coverage:
	pytest --cov=reliable_agent_runtime --cov-report=term-missing --cov-report=xml

lint:
	ruff format --check .
	ruff check .
	python scripts/quality_gate.py

format:
	ruff format .
	ruff check --fix .

openapi:
	python scripts/export_openapi.py

openapi-check:
	python scripts/export_openapi.py --check

quality: lint openapi-check coverage

acceptance:
	python benchmarks/reliability_scenarios.py --output artifacts/acceptance.json

clean:
	rm -rf .pytest_cache .ruff_cache htmlcov coverage.xml .coverage build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
