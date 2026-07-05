# PoC: CPA Document Intake Pipeline
# Run locally with: docker compose up --build
# Then visit http://localhost:8501

FROM python:3.11-slim

WORKDIR /app

# System deps for Streamlit + health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY src/ ./src/
COPY samples/ ./samples/
COPY tests/ ./tests/

# Ensure dirs exist for inbox/extracted/dlq (use bind-mounts in compose)
RUN mkdir -p docs/inbox docs/extracted docs/dlq

# Default command runs the runner once (compose.yml overrides for UI)
CMD ["python", "-m", "src.runner", "once"]
