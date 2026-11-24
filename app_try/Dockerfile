# Climate cube builder — interactive download/clip/remap app (marimo)
# Build from the repository root:  docker compose -f code/app/docker-compose.yml up --build
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends cdo wget ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy PATH=/opt/venv/bin:$PATH
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --extra dashboard
COPY code ./code

EXPOSE 2718
# data/ is mounted from the host, so downloads, runs and cubes stay on your machine
CMD ["marimo", "run", "code/app/processing_app.py", "--host", "0.0.0.0", "--port", "2718", "--headless", "--no-token"]
