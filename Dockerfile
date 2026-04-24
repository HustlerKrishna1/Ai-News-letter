FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY config.py main.py webui.py ./
COPY modules ./modules
COPY templates ./templates
COPY scripts ./scripts

RUN useradd --uid 10001 --create-home app \
    && mkdir -p /app/data /app/output \
    && chown -R app:app /app
USER app

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
# Default: start the dashboard. Override with `docker run ... python main.py` for a one-shot run.
CMD ["python", "main.py", "--serve", "--host", "0.0.0.0", "--port", "8000"]
