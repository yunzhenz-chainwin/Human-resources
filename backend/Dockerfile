FROM python:3.12-slim

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts
RUN pip install --no-cache-dir .

# Run as an unprivileged user.  Pre-create the storage directories (resumes,
# quarantine, candidate photos) so both the container layer and any named
# volumes mounted here inherit ownership writable by the app user.
RUN adduser --disabled-password --gecos "" app \
    && mkdir -p storage/resumes storage/quarantine storage/candidate-photos \
    && chown -R app:app /app/storage
USER app

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)"]
# Trust proxy headers so the app sees the real client IP (X-Forwarded-For) set
# by the nginx reverse proxy instead of the nginx container IP; per-IP login
# throttling and audit logging depend on it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
