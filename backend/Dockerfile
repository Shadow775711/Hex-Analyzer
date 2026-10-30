# Pinned by digest: a rebuild gets exactly the tested base image (Dependabot bumps it)
FROM python:3.15.0-slim@sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58

WORKDIR /app

# TMPDIR in the data volume: multipart uploads spool to disk there, not into the small /tmp tmpfs
# (the container runs with a read-only root fs — /app/data and /tmp are the only writable places)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    TMPDIR=/app/data/tmp

# Dependencies first (better layer caching); --require-hashes: only the exact locked files install
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

# Unprivileged user instead of root. It owns only the data dir — a fresh Docker volume
# inherits these permissions when first mounted. The code stays root-owned: the app can't modify itself.
RUN useradd --system --uid 10001 --home-dir /app app \
  && mkdir -p /app/data/tmp && chown -R app:app /app/data

COPY . .
USER app

EXPOSE 8000

# healthcheck without curl — fewer packages in the image, fewer vulnerabilities to patch
# (Host: localhost — must stay in ALLOWED_HOSTS)
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/ping', timeout=2)"]

CMD ["uvicorn", "main:app", "--host=0.0.0.0", "--port=8000"]
