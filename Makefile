.PHONY: help venv install run dev docker-build docker-run clean diagrams diagrams-local pitch

help:
	@echo "Available targets:"
	@echo "  venv           Create a Python virtual environment"
	@echo "  install        Install dependencies from requirements.txt (use after venv)"
	@echo "  run            Run the FastAPI app with uvicorn (reload, port 8000)"
	@echo "  docker-build   Build the Docker image (tag: room-matcher-backend)"
	@echo "  docker-run     Run the Docker image mapping port 8000"
	@echo "  diagrams       Render Mermaid diagrams in docs/ to SVG (requires Docker)"
	@echo "  diagrams-local Render Mermaid diagrams using local mmdc (no Docker)"
	@echo "  pitch          Generate pitch deck (installs deps, runs script with ARGS passthrough)"
	@echo "  clean          Remove __pycache__ and build artifacts"

diagrams:
	mkdir -p docs/svg
	docker run --rm -v "$(PWD)/docs:/data" minlag/mermaid-cli:10.9.0 -i /data/architecture_flow.mmd -o /data/svg/architecture_flow.svg
	docker run --rm -v "$(PWD)/docs:/data" minlag/mermaid-cli:10.9.0 -i /data/matching_sequence.mmd -o /data/svg/matching_sequence.svg

# Render diagrams locally without Docker (requires: npm i -g @mermaid-js/mermaid-cli)
diagrams-local:
	mkdir -p docs/svg
	mmdc -i docs/architecture_flow.mmd -o docs/svg/architecture_flow.svg
	mmdc -i docs/matching_sequence.mmd -o docs/svg/matching_sequence.svg

pitch: install
	venv/bin/python scripts/generate_pitch_deck.py $(ARGS)
