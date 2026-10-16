"""
Celery application.

    celery -A config worker -l info            (Linux/Docker)
    celery -A config worker -l info -P solo    (Windows: prefork isn't supported)
    celery -A config beat -l info              (exactly one beat process)
"""

import logging
import os

from celery import Celery
from celery.signals import task_failure

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

app = Celery("pleet")
# All CELERY_* Django settings configure Celery (see config/settings/base.py).
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@task_failure.connect
def log_task_failure(sender=None, task_id=None, exception=None, **kwargs):
    # Name and id only: task arguments can carry personal data.
    logging.getLogger("pleet.tasks").error(
        "Task failed",
        extra={"task": getattr(sender, "name", "?"), "task_id": task_id,
               "error": type(exception).__name__},
    )  # fmt: skip
