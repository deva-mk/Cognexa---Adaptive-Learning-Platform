# Single-container deployment: built React UI is served by the FastAPI app on one port.
FROM node:20-slim AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-hin tesseract-ocr-tam \
    tesseract-ocr-kan tesseract-ocr-mal && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY blockchain/abi blockchain/abi
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
COPY --from=ui /ui/dist frontend/dist
ENV DATA_DIR=/data SERVE_FRONTEND=true FRONTEND_DIST=/app/frontend/dist PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
WORKDIR /app/backend
CMD ["/entrypoint.sh"]
