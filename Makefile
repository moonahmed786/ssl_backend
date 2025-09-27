.PHONY: help venv install run dev docker-build docker-run clean

help:
	@echo "Available targets:"
	@echo "  venv           Create a Python virtual environment"
	@echo "  install        Install dependencies from requirements.txt (use after venv)"
	@echo "  run            Run the FastAPI app with uvicorn (reload, port 8000)"
	@echo "  docker-build   Build the Docker image (tag: room-matcher-backend)"
	@echo "  docker-run     Run the Docker image mapping port 8000"
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
