FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
LABEL org.opencontainers.image.source="https://github.com/hollis-yang/hmdp"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app
COPY --chown=10001:10001 app ./app
RUN mkdir -p /data/runs && chown -R 10001:10001 /data/runs
ENV PATH="/app/.venv/bin:${PATH}"
USER 10001:10001
EXPOSE 8090
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
