FROM python:3.12-slim

WORKDIR /app

COPY requirements-proxy.txt .
RUN pip install --no-cache-dir -r requirements-proxy.txt

COPY proxy.py db.py pricing.yaml ./

ENV PORT=8000
EXPOSE 8000

CMD uvicorn proxy:app --host 0.0.0.0 --port ${PORT}
