FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget gnupg \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
    libffi-dev libcairo2 libpq5 \
    # Chrome runtime deps for Playwright channel='chrome'
    libnss3 libnspr4 libdbus-1-3 libxkbcommon0 libgbm1 \
    libasound2 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    fonts-liberation \
    # Document conversion tools
    libreoffice-writer libreoffice-calc libreoffice-impress \
    pandoc calibre && \
    # Install Google Chrome stable (for channel='chrome' WAF bypass)
    wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt-get install -y /tmp/chrome.deb && rm /tmp/chrome.deb && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Builder stage ---
FROM base AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# --- Runtime stage ---
FROM base AS runtime

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/api /app/api
COPY --from=builder /app/config /app/config
COPY --from=builder /app/alembic /app/alembic
COPY --from=builder /app/alembic.ini /app/alembic.ini
COPY --from=builder /app/scripts /app/scripts
COPY --from=builder /app/static /app/static

RUN chmod +x /app/scripts/entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 CMD curl -f http://localhost:8000/health || exit 1

CMD ["/app/scripts/entrypoint.sh"]
