# The replay server's image, for Azure Container Apps. Build from the repo root:
#   docker build -t seize-the-game-api .
# CPU only and small: just what the server imports (FastAPI, Cosmos DB and Azure Monitor SDKs). It makes no model
# calls, so no Agent Framework, openai or evaluation packages; and nothing for the video path (video/.venv).
# The match files are read from /app/samples (PITCH_SAMPLES).

FROM python:3.12-slim AS build
WORKDIR /src
COPY backend/pyproject.toml backend/
COPY backend/pitch_insights backend/pitch_insights
RUN pip install --no-cache-dir --prefix=/install ./backend

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PITCH_SAMPLES=/app/samples
COPY --from=build /install /usr/local
COPY samples /app/samples
RUN useradd --system --no-create-home --uid 10001 app
USER app
WORKDIR /app
EXPOSE 8000
# Container Apps' ingress terminates TLS and sets X-Forwarded-For; the profile API's rate limit reads it (profiles.py).
CMD ["uvicorn", "pitch_insights.server:app", "--host", "0.0.0.0", "--port", "8000"]
