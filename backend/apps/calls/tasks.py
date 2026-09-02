from __future__ import annotations

import logging
import uuid

import httpx
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import CallEvent
from .services import download_recording, lookup_recording

logger = logging.getLogger(__name__)


@shared_task(
    name="calls.resolve_recording",
    bind=True,
    max_retries=5,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=90,
    time_limit=120,
)
def resolve_recording(self, event_id: str):
    try:
        event = CallEvent.objects.select_related("dialer").get(pk=event_id)
    except CallEvent.DoesNotExist:
        logger.warning(
            "Call event disappeared before recording lookup",
            extra={"event_id": event_id},
        )
        return {"status": "missing"}
    if event.recording_download_status == CallEvent.Status.DOWNLOADED:
        return {"status": "already_downloaded"}
    if not event.lead_id.isdigit():
        CallEvent.objects.filter(pk=event.pk).update(
            recording_lookup_status=CallEvent.Status.SKIPPED,
            recording_download_status=CallEvent.Status.SKIPPED,
            recording_lookup_last_error="A numeric lead_id was not supplied",
        )
        return {"status": "skipped"}
    attempt = self.request.retries + 1
    try:
        recording = lookup_recording(event.dialer, event)
    except ValidationError as exc:
        CallEvent.objects.filter(pk=event.pk).update(
            recording_lookup_status=CallEvent.Status.FAILED,
            recording_download_status=CallEvent.Status.SKIPPED,
            recording_lookup_last_error=str(exc)[:1000],
        )
        logger.error(
            "Invalid dialer configuration prevented recording lookup",
            extra={"event_id": event_id, "error": str(exc)},
        )
        return {"status": "failed"}
    except httpx.HTTPError as exc:
        recording = None
        error = str(exc)[:1000]
    else:
        error = "Recording URL is not available yet"
    if recording is None:
        CallEvent.objects.filter(pk=event.pk).update(
            recording_lookup_status=CallEvent.Status.RETRYING,
            recording_lookup_attempts=attempt,
            recording_lookup_last_error=error,
        )
        if self.request.retries >= self.max_retries:
            CallEvent.objects.filter(pk=event.pk).update(
                recording_lookup_status=CallEvent.Status.NOT_FOUND,
                recording_download_status=CallEvent.Status.SKIPPED,
            )
            return {"status": "not_found"}
        delays = settings.RECORDING_RETRY_DELAYS
        countdown = delays[min(self.request.retries, len(delays) - 1)]
        logger.warning(
            "Recording lookup will retry",
            extra={
                "event_id": event_id,
                "attempt": attempt,
                "countdown": countdown,
                "error": error,
            },
        )
        raise self.retry(exc=RuntimeError(error), countdown=countdown)
    with transaction.atomic():
        locked = CallEvent.objects.select_for_update().get(pk=event.pk)
        locked.source_recording_id = (
            recording.recording_id or locked.source_recording_id
        )
        locked.recording_source_url = recording.location
        locked.recording_lookup_status = CallEvent.Status.FOUND
        locked.recording_lookup_attempts = attempt
        locked.recording_lookup_last_error = ""
        locked.save(
            update_fields=[
                "source_recording_id",
                "recording_source_url",
                "recording_lookup_status",
                "recording_lookup_attempts",
                "recording_lookup_last_error",
            ]
        )
        transaction.on_commit(lambda: fetch_recording.delay(str(locked.pk)))
    return {"status": "found"}


@shared_task(
    name="calls.fetch_recording",
    bind=True,
    max_retries=5,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=240,
    time_limit=270,
)
def fetch_recording(self, event_id: str):
    try:
        event = CallEvent.objects.select_related("dialer").get(pk=event_id)
    except CallEvent.DoesNotExist:
        logger.warning(
            "Call event disappeared before recording download",
            extra={"event_id": event_id},
        )
        return {"status": "missing"}
    if (
        event.recording_download_status == CallEvent.Status.DOWNLOADED
        and event.recording_path
    ):
        return {"status": "already_downloaded"}
    claimed = CallEvent.objects.filter(
        pk=event.pk,
        recording_download_status__in=[
            CallEvent.Status.PENDING,
            CallEvent.Status.RETRYING,
            CallEvent.Status.FAILED,
        ],
    ).update(recording_download_status=CallEvent.Status.DOWNLOADING)
    if not claimed:
        return {"status": "already_processing"}
    recording_uuid = event.recording_uuid or uuid.uuid4()
    CallEvent.objects.filter(pk=event.pk).update(
        recording_uuid=recording_uuid,
        recording_download_status=CallEvent.Status.DOWNLOADING,
        recording_download_attempts=self.request.retries + 1,
        recording_download_last_error="",
    )
    try:
        path, size, sha256 = download_recording(
            event.dialer, event.recording_source_url, recording_uuid
        )
    except (ValidationError, SoftTimeLimitExceeded) as exc:
        CallEvent.objects.filter(pk=event.pk).update(
            recording_download_status=CallEvent.Status.FAILED,
            recording_download_last_error=str(exc)[:1000],
        )
        logger.error(
            "Recording download permanently failed",
            extra={"event_id": event_id, "error": str(exc)},
        )
        raise
    except (httpx.HTTPError, OSError) as exc:
        final_attempt = self.request.retries >= self.max_retries
        CallEvent.objects.filter(pk=event.pk).update(
            recording_download_status=CallEvent.Status.FAILED
            if final_attempt
            else CallEvent.Status.RETRYING,
            recording_download_last_error=str(exc)[:1000],
        )
        logger.warning(
            "Recording download failed",
            extra={
                "event_id": event_id,
                "attempt": self.request.retries + 1,
                "error": str(exc),
            },
        )
        if final_attempt:
            raise
        raise self.retry(exc=exc, countdown=min(120, 2 ** (self.request.retries + 1)))
    CallEvent.objects.filter(pk=event.pk).update(
        recording_path=path,
        recording_size_bytes=size,
        recording_sha256=sha256,
        recording_download_status=CallEvent.Status.DOWNLOADED,
        recording_download_last_error="",
    )
    logger.info(
        "Recording downloaded",
        extra={
            "event_id": event_id,
            "recording_uuid": str(recording_uuid),
            "bytes": size,
        },
    )
    return {"status": "downloaded", "bytes": size}
