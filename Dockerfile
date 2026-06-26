# Single-container build: the FastAPI core serves the API *and* the built
# dashboard, so one image / one URL runs the whole thing. Used by free hosts
# like Render or Hugging Face Spaces (Docker).

# 1) Build the dashboard as a static site.
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN TITAN_STATIC=1 npm run build

# 2) Python image runs the core and serves the static dashboard from frontend/out.
FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=frontend /app/frontend/out frontend/out

# Public deploys should require login. Set TITAN_USERNAME / TITAN_PASSWORD /
# TITAN_SECRET as host settings (never bake secrets into the image).
ENV TITAN_REQUIRE_AUTH=1

WORKDIR /app/backend
# HF Spaces (Docker) expects the app on port 7860 (matches app_port in README).
# Render and other hosts inject $PORT, which overrides the default below.
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
