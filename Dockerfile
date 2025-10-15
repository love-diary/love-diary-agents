FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
# - gcc: Required for building Python packages
# - libpq-dev: Required for asyncpg (PostgreSQL async driver)
# - curl: For healthcheck
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY agent_service/ ./agent_service/

# Create non-root user for security
RUN useradd -m -u 1000 agentuser && \
    mkdir -p /app/logs && \
    chown -R agentuser:agentuser /app

# Switch to non-root user
USER agentuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uvicorn", "agent_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
