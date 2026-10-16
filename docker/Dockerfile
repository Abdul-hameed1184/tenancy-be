# syntax=docker/dockerfile:1

# ---- build stage: compile/install dependencies into a self-contained venv -------------
FROM python:3.14-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements/ requirements/
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements/production.txt

# ---- runtime stage: only the venv and the code, running as a non-root user ------------
FROM python:3.14-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production
RUN useradd --system --uid 1000 --create-home pleet
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=pleet:pleet . .

# collectstatic needs importable settings, not real secrets: throwaway build-only values.
RUN SECRET_KEY="build-only-not-a-secret-build-only-not-a-secret-build-only" \
    ALLOWED_HOSTS="build" \
    python manage.py collectstatic --noinput \
 && chown -R pleet:pleet /app/staticfiles

USER pleet
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/', timeout=2)"

# One ASGI server for HTTP + WebSocket: gunicorn supervises uvicorn workers.
CMD ["gunicorn", "config.asgi:application", "-c", "docker/gunicorn.conf.py"]
