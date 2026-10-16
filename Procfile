web: gunicorn config.asgi:application -k uvicorn_worker.UvicornWorker --bind 0.0.0.0:$PORT --workers 2 --timeout 120
worker: celery -A config worker --loglevel=info --concurrency=2
beat: celery -A config beat --loglevel=info
