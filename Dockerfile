FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd -m -u 10001 jarvis
# Everything comes from the hash-locked requirements.lock (`make lock` regenerates it from
# pyproject.toml + requirements-build.in): pip refuses any artifact whose sha256 differs from
# the lock, so a hijacked package index or a tampered wheel cannot reach the image. The lock
# also pins pip itself, setuptools and wheel (the base image's pip only bootstraps them), and
# the app builds with --no-build-isolation against those locked build tools and --no-deps, so
# nothing is ever fetched outside the lock.
COPY pyproject.toml README.md requirements.lock ./
RUN pip install --require-hashes -r requirements.lock
COPY src ./src
# R3: the home kit that GET /v1/home/kit zips (with src/jarvis/homebridge)
COPY deploy/home ./deploy/home
# Where kit.build finds deploy/home and src (the installed package sits in site-packages)
ENV HOME_KIT_ROOT=/app
# R6.1 D4: the build time the Vitals "About JARVIS" line shows (jarvis.about), stamped HERE at image
# build (never at request time); package data carries it into the installed package.
RUN date -u +%Y-%m-%dT%H:%M:%SZ > src/jarvis/BUILD_DATE
RUN pip install --no-build-isolation --no-deps .
USER jarvis
EXPOSE 8000
# Cloud Run (and most PaaS) inject $PORT; default 8000 for local/docker-compose.
ENV PORT=8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000')).status==200 else 1)"
CMD ["sh", "-c", "exec jarvis serve --host 0.0.0.0 --port ${PORT}"]
