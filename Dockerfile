FROM node:22-bookworm-slim AS frontend
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8000
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/ ./backend/
COPY scripts/run.py ./scripts/run.py
COPY --from=frontend /ui/dist ./frontend/dist
RUN useradd --create-home --uid 10001 appuser
USER appuser
EXPOSE 8000
CMD ["python", "scripts/run.py"]
