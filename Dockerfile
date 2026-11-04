# One container: builds the React app, then serves it and the API with waitress.
# Works on Render, Railway, Fly.io or any Docker host. Set GNANI_* and other settings as environment variables.

FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist
ENV PORT=8000 TRUST_PROXY=1 FRONTEND_DIST=/app/frontend/dist PILOT_LOG_PATH=/data/pilot_log.jsonl
EXPOSE 8000
CMD ["python", "serve.py"]
