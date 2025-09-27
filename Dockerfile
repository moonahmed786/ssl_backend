# syntax=docker/dockerfile:1

FROM python:3.12-slim

WORKDIR /app

# System deps (optional): add any build deps if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency list first to leverage Docker layer cache
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source and datasets
COPY app.py ./
COPY synthetic_roommate_profiles_pakistan_400.json ./
COPY housing_listings_pakistan_400.json ./

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
