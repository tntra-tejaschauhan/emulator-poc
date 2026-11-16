FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN useradd --create-home --uid 10000 appuser && chown -R appuser:appuser /srv/app
USER appuser

EXPOSE 8000

# Overridden per service in docker-compose.yml.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"]
