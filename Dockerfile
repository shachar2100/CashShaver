FROM python:3.12-slim

WORKDIR /app

# Slim images need CA certs for MongoDB Atlas TLS (mongodb+srv).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-proxy.txt .
RUN pip install --no-cache-dir -r requirements-proxy.txt

COPY proxy.py db.py pricing.yaml ./

ENV PORT=8000
EXPOSE 8000

# Cloud Run injects PORT at runtime; shell form keeps it expandable.
CMD ["sh", "-c", "uvicorn proxy:app --host 0.0.0.0 --port ${PORT}"]
