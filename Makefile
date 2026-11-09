UV ?= uv
PORT ?= 8000
STUDIO_PORT ?= 3000
export UV_CACHE_DIR ?= /tmp/swarmcircuit-uv-cache

.PHONY: bootstrap init-local init-mock db-init server server-mock demo demo-control demo-payment demo-studio studio studio-install studio-check control-contract payment-contract studio-contract test lint typecheck check
bootstrap:
	$(UV) sync --frozen --all-extras
init-local:
	python3 scripts/init_local.py
init-mock:
	python3 scripts/init_local.py --mock
db-init:
	$(UV) run --frozen python scripts/db_init.py
server:
	SWARM_DEMO_API_URL=http://127.0.0.1:$(PORT) $(UV) run --frozen uvicorn swarmcircuit_server.app:app --host 127.0.0.1 --port $(PORT) --workers 1 --env-file .env
server-mock:
	SWARM_DEMO_API_URL=http://127.0.0.1:$(PORT) $(UV) run --frozen python -c "from dotenv import load_dotenv; load_dotenv('.env'); load_dotenv('.env.mock', override=True); import uvicorn; uvicorn.run('swarmcircuit_server.app:app', host='127.0.0.1', port=$(PORT), workers=1)"
demo:
	$(UV) run --frozen python -c "from dotenv import load_dotenv; load_dotenv('.env'); from examples.stalled_dependency import main; main()" --seed $(or $(SEED),7)
demo-control:
	$(UV) run --frozen python -c "from dotenv import load_dotenv; load_dotenv('.env'); from examples.cooperative_control import main; main()"
demo-payment:
	$(UV) run --frozen --extra payments python -c "from dotenv import load_dotenv; load_dotenv('.env'); load_dotenv('.env.mock', override=True); from examples.payment_visibility import main; main()"
control-contract:
	$(UV) run --frozen python scripts/export_control_contract.py
payment-contract:
	$(UV) run --frozen python scripts/export_payment_contract.py
studio-contract:
	$(UV) run --frozen python scripts/export_studio_contract.py
studio-install:
	npm --prefix apps/studio ci
studio:
	STUDIO_PORT=$(STUDIO_PORT) npm --prefix apps/studio run dev
studio-check:
	npm --prefix apps/studio run check
demo-studio:
	$(UV) run --frozen python -c "from dotenv import load_dotenv; load_dotenv('.env'); from examples.studio_checkpoint import main; main()"
test:
	$(UV) run --frozen pytest -q
lint:
	$(UV) run --frozen ruff check .
	$(UV) run --frozen ruff format --check .
typecheck:
	$(UV) run --frozen mypy
check: lint typecheck test

.PHONY: research research-llm research-verify demo-containment research-contract
research:
	$(UV) run --frozen python -m swarmcircuit_server.research.cli run --api $(or $(SWARM_API_URL),http://127.0.0.1:18005) --seeds $(or $(SEEDS),30)
research-llm:
	$(UV) run --frozen python -m swarmcircuit_server.research.cli llm --api $(or $(SWARM_API_URL),http://127.0.0.1:18005) --seeds 1 --scenarios retry_cascade --max-calls $(or $(MAX_CALLS),30)
research-verify:
	$(UV) run --frozen python -m swarmcircuit_server.research.cli verify --output $(EXPERIMENT_DIR)
demo-containment:
	$(UV) run --frozen python -c "from dotenv import load_dotenv; load_dotenv('.env'); from examples.containment_demo import main; main()"
research-contract:
	$(UV) run --frozen python scripts/export_research_contract.py
