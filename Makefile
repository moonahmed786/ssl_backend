.PHONY: help venv install run dev docker-build docker-run clean diagrams diagrams-local pitch final

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
	@echo "  final          Generate final 7-slide presentation (ARGS passthrough)"
	@echo "  clean          Remove __pycache__ and build artifacts"

diagrams:
	mkdir -p docs/svg
	mkdir -p docs/png
	docker run --rm -v "$(PWD)/docs:/data" minlag/mermaid-cli:10.9.0 -i /data/architecture_flow.mmd -o /data/svg/architecture_flow.svg
	docker run --rm -v "$(PWD)/docs:/data" minlag/mermaid-cli:10.9.0 -i /data/matching_sequence.mmd -o /data/svg/matching_sequence.svg
	docker run --rm -v "$(PWD)/docs:/data" minlag/mermaid-cli:10.9.0 -i /data/solution_overview.mmd -o /data/svg/solution_overview.svg
	docker run --rm -v "$(PWD)/docs:/data" minlag/mermaid-cli:10.9.0 -i /data/solution_overview.mmd -o /data/png/solution_overview.png
	docker run --rm -v "$(PWD)/docs:/data" minlag/mermaid-cli:10.9.0 -i /data/agentic_flow.mmd -o /data/svg/agentic_flow.svg
	docker run --rm -v "$(PWD)/docs:/data" minlag/mermaid-cli:10.9.0 -i /data/agentic_flow.mmd -o /data/png/agentic_flow.png

diagrams-local:
	mkdir -p docs/svg
	mkdir -p docs/png
	mmdc -i docs/architecture_flow.mmd -o docs/svg/architecture_flow.svg
	mmdc -i docs/matching_sequence.mmd -o docs/svg/matching_sequence.svg
	mmdc -i docs/solution_overview.mmd -o docs/svg/solution_overview.svg
	mmdc -i docs/solution_overview.mmd -o docs/png/solution_overview.png
	mmdc -i docs/agentic_flow.mmd -o docs/svg/agentic_flow.svg
	mmdc -i docs/agentic_flow.mmd -o docs/png/agentic_flow.png

pitch: install
	venv/bin/python scripts/generate_pitch_deck.py $(ARGS)

final: install
	venv/bin/python scripts/generate_final_presentation.py $(ARGS)
