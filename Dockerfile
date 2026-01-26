# Multi-stage Dockerfile - builds dashboard and runs bot + API with supervisord

# Stage 1: Build the React dashboard
FROM node:20-slim AS dashboard-builder

WORKDIR /app/dashboard

# Copy package files first for layer caching
COPY dashboard/package*.json ./

# Install dependencies
RUN npm ci

# Copy source and build
COPY dashboard/ ./
RUN npm run build


# Stage 2: Production Python image
FROM python:3.11-slim AS production

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock* ./

# Install dependencies
RUN uv sync --no-dev

# Copy supervisor config and entrypoint
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Copy source code
COPY src/ ./src/

# Copy default config
COPY config/ ./config/

# Copy pre-built dashboard from builder stage
COPY --from=dashboard-builder /app/dashboard/dist/ ./dashboard/dist/

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
