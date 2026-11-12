# The JARVIS home bridge image (R3 D3). Built on the owner's laptop from this kit.
# Only hash-locked packages are installed; the bridge source is the kit's bridge-src folder.
# The base image's digest is recorded by setup-wsl.sh in images.env (BASE_IMAGE) after the first pull.
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/app
# R11.1: the picture decoder never allocates for more than 50 megapixels, whatever a file says
# (the bridge itself checks every picture's size from its header before decoding it)
ENV OPENCV_IO_MAX_IMAGE_PIXELS=50000000
WORKDIR /app
# /models: the two face model files; /photos: the owner's photo folder. Both are mounted read-only.
RUN useradd --no-create-home --uid 10001 bridge && mkdir /data /models /photos && chown 10001:10001 /data
COPY bridge-requirements.txt ./
RUN pip install --require-hashes --no-deps -r bridge-requirements.txt
COPY bridge-src/ /app/
USER 10001
EXPOSE 8099 8098
VOLUME ["/data"]
CMD ["python", "-m", "jarvis.homebridge"]
