FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd -m -u 10001 jarvis
# Dependencies come from the hash-locked requirements.lock (`make lock` regenerates it from
# pyproject.toml): pip refuses any artifact whose sha256 differs from the lock, so a hijacked
# package index or a tampered wheel cannot reach the image. The app itself installs with
# --no-deps so nothing can be pulled in outside the lock.
COPY pyproject.toml README.md requirements.lock ./
RUN pip install --upgrade pip && pip install --require-hashes -r requirements.lock
COPY src ./src
RUN pip install --no-deps .
USER jarvis
EXPOSE 8000
# Cloud Run (and most PaaS) inject $PORT; default 8000 for local/docker-compose.
ENV PORT=8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000')).status==200 else 1)"
CMD ["sh", "-c", "exec jarvis serve --host 0.0.0.0 --port ${PORT}"]
