FROM python:3.11-slim

# uv is the ONLY package installed via pip — everything else goes through uv
RUN pip install uv

WORKDIR /app

# Install dependencies first (cache layer — only re-runs if pyproject.toml or uv.lock changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Create volume mount point for persistent feedback DB
RUN mkdir -p /app/data

EXPOSE 8001

# Health check for container orchestration — validates app is alive AND all
# critical components (postgres, llm, checkpointer) are healthy.
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
  CMD python -c "import urllib.request,json,os; resp=urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8001')+'/health'); data=json.loads(resp.read()); exit(0 if data['status']=='healthy' else 1)"

CMD ["uv", "run", "python", "main.py"]
