.PHONY: test coverage makemigrations auto-migrations migrate rollback rollaback check fix

test:
	uv run python -m pytest tests -v

coverage:
	uv run python -m pytest tests -v --cov=api --cov-report=term-missing --cov-report=xml

makemigrations:
	@read -p "Enter migration message: " message; \
	uv run alembic revision --autogenerate -m "$$message"

auto-migrations: makemigrations

migrate:
	uv run alembic upgrade head

rollback:
	uv run alembic downgrade -1

check:
	@echo "Running checks..."; \
	echo "Running ruff check..."; \
	uv run ruff check .; \
	ruff_check_exit_code=$$?; \
	echo "Running ruff format --check..."; \
	uv run ruff format --check .; \
	ruff_format_exit_code=$$?; \
	echo "Running ty check..."; \
	uv run ty check .; \
	ty_check_exit_code=$$?; \
	if [ $$ruff_check_exit_code -ne 0 ] || [ $$ruff_format_exit_code -ne 0 ] || [ $$ty_check_exit_code -ne 0 ]; then \
		echo "Checks failed."; \
		exit 1; \
	fi

fix:
	@echo "Running ruff fix..."
	@ruff check --fix
	@echo "Running ruff format..."
	@ruff format .
