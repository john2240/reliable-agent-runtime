FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    RAR_HOST=0.0.0.0 \
    RAR_PORT=8000

WORKDIR /app

RUN groupadd --system runtime && useradd --system --gid runtime --create-home runtime

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --upgrade pip && python -m pip install .

RUN mkdir -p /app/data && chown -R runtime:runtime /app
USER runtime

EXPOSE 8000
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)" || exit 1

CMD ["reliable-agent-runtime"]
