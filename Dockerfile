FROM node:24-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY scripts/ ./scripts/
COPY configs/ ./configs/
COPY output/models/ ./output/models/
COPY --from=frontend-build /app/frontend/dist/ ./frontend/dist/

EXPOSE 10000
CMD ["sh", "-c", "python scripts/run_api.py --host 0.0.0.0 --port ${PORT:-10000} --no-browser"]
