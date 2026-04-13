FROM python:3.11-slim

# uv is the ONLY package installed via pip — everything else goes through uv
RUN pip install uv

WORKDIR /app

# Install dependencies first (cache layer — only re-runs if pyproject.toml or uv.lock changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Create volume mount points for persistent data
RUN mkdir -p /app/vector_store /app/data

EXPOSE 8001

# Health check for container orchestration
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"

CMD ["uv", "run", "python", "main.py"]
