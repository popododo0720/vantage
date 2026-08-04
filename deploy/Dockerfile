FROM node:22-alpine AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    VANTAGE_ENVIRONMENT=production \
    VANTAGE_STORE_BACKEND=redis
WORKDIR /app
RUN addgroup --system vantage && adduser --system --ingroup vantage vantage
COPY pyproject.toml README.md ./
COPY backend/ ./backend/
RUN pip install --no-cache-dir ".[openstack,platform]"
COPY --from=frontend /src/frontend/dist ./frontend/dist
USER vantage
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)"]
CMD ["uvicorn", "vantage_bff.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
