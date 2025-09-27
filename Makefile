.PHONY: help venv install run dev docker-build docker-run clean diagrams

help:
	@echo "Available targets:"
	@echo "  venv           Create a Python virtual environment"
	@echo "  install        Install dependencies from requirements.txt (use after venv)"
	@echo "  run            Run the FastAPI app with uvicorn (reload, port 8000)"
	@echo "  docker-build   Build the Docker image (tag: room-matcher-backend)"
	@echo "  docker-run     Run the Docker image mapping port 8000"
	@echo "  diagrams       Render Mermaid diagrams in docs/ to SVG (requires Docker)"
	@echo "  clean          Remove __pycache__ and build artifacts"

venv:
	python3 -m venv venv

install:
	venv/bin/pip install -r requirements.txt

run:
	venv/bin/uvicorn app:app --reload --host 127.0.0.1 --port 8000

# Docker

docker-build:
	docker build -t room-matcher-backend .

docker-run:
	docker run --rm -p 8000:8000 room-matcher-backend

clean:
	rm -rf __pycache__ */__pycache__ build dist *.egg-info

diagrams:
	mkdir -p docs/svg
	docker run --rm -v "$(PWD)/docs:/data" minlag/mermaid-cli:10.9.0 -i /data/architecture_flow.mmd -o /data/svg/architecture_flow.svg
	docker run --rm -v "$(PWD)/docs:/data" minlag/mermaid-cli:10.9.0 -i /data/matching_sequence.mmd -o /data/svg/matching_sequence.svg
