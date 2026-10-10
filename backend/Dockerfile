# ---- builder: install dependencies with build tools ----
FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock .
# CPU-only torch first. PyPI's Linux torch pulls about 4 GB of NVIDIA CUDA
# libraries and Triton that a CPU-only host can never use. Installed into the
# venv first, it already satisfies the lock's torch== pin, so the second
# install leaves it alone.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==$(grep -E '^torch==' requirements.lock | cut -d= -f3)" \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.lock

# ---- production: lean runtime image ----
FROM python:3.13-slim AS production

RUN useradd --uid 1000 --no-create-home --shell /bin/false appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

EXPOSE 8000

USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
