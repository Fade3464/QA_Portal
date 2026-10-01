from celery.signals import task_postrun, task_prerun
from django.conf import settings

from .db_metrics import SQLCollector


@task_prerun.connect(weak=False)
def begin_database_metrics(task_id=None, task=None, **kwargs):
    if not task or not settings.DB_METRICS_ENABLED or not settings.DB_METRICS_REDIS_URL:
        return
    collector = SQLCollector("worker", task.name)
    collector.__enter__()
    # request is local to the execution, including concurrent/eager tasks.
    task.request._database_metrics = collector


@task_postrun.connect(weak=False)
def finish_database_metrics(task=None, **kwargs):
    collector = getattr(task.request, "_database_metrics", None) if task else None
    if collector:
        del task.request._database_metrics
        collector.__exit__(None, None, None)
