# The JARVIS home bridge image (R3 D3). Built on the owner's laptop from this kit.
# Only hash-locked packages are installed; the bridge source is the kit's bridge-src folder.
# The base image's digest is recorded by setup-wsl.sh in images.env (BASE_IMAGE) after the first pull.
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/app
WORKDIR /app
RUN useradd --no-create-home --uid 10001 bridge && mkdir /data && chown 10001:10001 /data
COPY bridge-requirements.txt ./
RUN pip install --require-hashes --no-deps -r bridge-requirements.txt
COPY bridge-src/ /app/
USER 10001
EXPOSE 8099 8098
VOLUME ["/data"]
CMD ["python", "-m", "jarvis.homebridge"]
