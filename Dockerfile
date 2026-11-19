FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_HTTP_TIMEOUT=300

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev

ARG BAKE_MODELS=0
RUN if [ "$BAKE_MODELS" = "1" ]; then \
        ECO_MODELS=/opt/eco-models/models /app/.venv/bin/eco setup --yes; \
    else \
        mkdir -p /opt && ln -s /data /opt/eco-models; \
    fi

RUN useradd --uid 10001 --create-home eco \
    && mkdir -p /data \
    && chown eco:eco /data
USER eco
ENV PATH=/app/.venv/bin:$PATH ECO_DATA=/data ECO_MODELS=/opt/eco-models/models PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" || exit 1
CMD ["eco", "web", "--host", "0.0.0.0", "--port", "8000", "--no-browser"]
