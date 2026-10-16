# Load Celery with Django so @shared_task binds to this app and `.delay()` uses its broker.
from .celery import app as celery_app

__all__ = ["celery_app"]
