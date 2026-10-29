from __future__ import annotations

import logging
import uuid
from datetime import timedelta

import httpx
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import CallEvent
from .preset_lookup import lookup_sale_preset
from .services import download_recording, lookup_recording, recording_duration_seconds
from apps.notifications.services import (
    queue_missing_preset_notification,
    resolve_missing_preset_notification,
)

logger = logging.getLogger(__name__)


# The recordings queue uses Redis priority emulation, where lower numbers are
# consumed first. Keep fresh lookups responsive while downloads drain in the
# background without introducing another queue or worker topology.
RECORDING_RESOLVE_PRIORITY = 0
RECORDING_FETCH_PRIORITY = 9


def _http_status(exc) -> int | None:
    return exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None


def _refresh_recording_after_failure(event, reason):
    """Re-query VICIdial because recording hosts can replace a stale URL."""
    try:
        recording = lookup_recording(event.dialer, event)
    except (ValidationError, httpx.HTTPError) as exc:
        logger.warning(
            "Recording URL refresh failed after a download failure",
            extra={
                "event_id": str(event.pk),
                "reason": reason,
                "error": str(exc),
            },
        )
        return None
    if recording is None:
        logger.info(
            "Recording URL is not yet available after a download failure",
            extra={"event_id": str(event.pk), "reason": reason},
        )
        return None

    CallEvent.objects.filter(pk=event.pk).update(
        source_recording_id=recording.recording_id or event.source_recording_id,
        recording_source_url=recording.location,
        recording_lookup_status=CallEvent.Status.FOUND,
        recording_lookup_attempts=event.recording_lookup_attempts + 1,
        recording_lookup_last_error="",
    )
    logger.info(
        "Recording URL refreshed after a download failure",
        extra={
            "event_id": str(event.pk),
            "reason": reason,
            "url_changed": recording.location != event.recording_source_url,
        },
    )
    return recording


PRESET_LOOKUP_RETRY_DELAYS = (15, 30, 45, 60)


@shared_task(
    name="calls.resolve_sale_preset",
    bind=True,
    max_retries=len(PRESET_LOOKUP_RETRY_DELAYS),
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=45,
    time_limit=60,
)
def resolve_sale_preset(self, event_id: str):
    """Resolve the newest XFER_3WAY preset for a newly-disposed SALE call.

    VICIdial's User Stats report can lag behind the disposition callback, so the
    task retries for roughly 2.5 minutes before notifying editor-enabled PMs.
    Existing historical SALE rows are never backfilled because this task is only
    queued by new disposition/editor transitions.
    """
    try:
        event = CallEvent.objects.select_related("dialer", "dialer__branch", "branch").get(pk=event_id)
    except CallEvent.DoesNotExist:
        return {"status": "missing"}

    if event.disposition.upper() != "SALE":
        resolve_missing_preset_notification(event)
        return {"status": "not_sale"}
    if event.preset:
        resolve_missing_preset_notification(event)
        return {"status": "already_resolved", "preset": event.preset}

    try:
        result = lookup_sale_preset(event.dialer, event)
    except ValidationError as exc:
        logger.warning(
            "SALE preset lookup configuration is unavailable",
            extra={"event_id": event_id, "error": str(exc)},
        )
        queue_missing_preset_notification(event)
        return {"status": "configuration_error", "error": str(exc)}
    except httpx.HTTPError as exc:
        result = None
        error = str(exc)[:1000]
    else:
        error = "No matching XFER_3WAY preset is available yet"

    if result is not None:
        updated = CallEvent.objects.filter(
            pk=event.pk, disposition__iexact="SALE", preset__isnull=True
        ).update(preset=result.preset)
        event.refresh_from_db(fields=["preset", "disposition"])
        if event.disposition.upper() == "SALE" and event.preset:
            resolve_missing_preset_notification(event)
            logger.info(
                "Resolved VICIdial SALE preset",
                extra={
                    "event_id": event_id,
                    "preset": event.preset,
                    "occurred_at": result.occurred_at.isoformat(),
                    "dialed": result.dialed,
                    "updated": bool(updated),
                },
            )
            return {"status": "resolved", "preset": event.preset}
        return {"status": "superseded"}

    if self.request.retries >= self.max_retries:
        queue_missing_preset_notification(event)
        logger.warning(
            "SALE call has no preset after VICIdial lookup retries",
            extra={"event_id": event_id, "error": error},
        )
        return {"status": "not_found"}

    countdown = PRESET_LOOKUP_RETRY_DELAYS[
        min(self.request.retries, len(PRESET_LOOKUP_RETRY_DELAYS) - 1)
    ]
    logger.info(
        "SALE preset lookup will retry",
        extra={
            "event_id": event_id,
            "attempt": self.request.retries + 1,
            "countdown": countdown,
            "error": error,
        },
    )
    raise self.retry(exc=RuntimeError(error), countdown=countdown)


@shared_task(name="calls.mark_stale_calls")
def mark_stale_calls(batch_size: int = 500):
    """Mark provisional Start Call records stale after two hours.

    Rows are locked in small batches so a final disposition racing this sweep
    either wins first (and is skipped here) or cleanly recovers the STALE row
    immediately afterward. No recording or QA work is started for stale calls.
    """
    cutoff = timezone.now() - timedelta(hours=2)
    with transaction.atomic():
        events = list(
            CallEvent.objects.select_for_update(skip_locked=True)
            .filter(
                event_type=CallEvent.EventType.DISPOSITION,
                disposition="INCALL",
                stale=False,
                received_at__lte=cutoff,
            )
            .order_by("received_at")[: max(1, min(batch_size, 5000))]
        )
        if not events:
            return {"status": "ok", "marked_stale": 0}

        for event in events:
            event.disposition = "STALE"
            event.stale = True
            event.recording_lookup_status = CallEvent.Status.SKIPPED
            event.recording_download_status = CallEvent.Status.SKIPPED
            event.recording_lookup_last_error = (
                "Call remained INCALL for more than two hours without a disposition"
            )
            event.recording_download_last_error = (
                "Recording processing is not applicable to stale calls"
            )

        CallEvent.objects.bulk_update(
            events,
            [
                "disposition",
                "stale",
                "recording_lookup_status",
                "recording_download_status",
                "recording_lookup_last_error",
                "recording_download_last_error",
            ],
        )

    logger.warning(
        "Marked undispositioned VICIdial calls stale",
        extra={"count": len(events), "cutoff": cutoff.isoformat()},
    )
    return {"status": "ok", "marked_stale": len(events)}


@shared_task(
    name="calls.resolve_recording",
    bind=True,
    max_retries=5,
    acks_late=True,
    reject_on_worker_lost=True,
    # Intentionally above normal production volume so backlog recovery does
    # not starve fresh recording work.
    rate_limit="20/s",
    priority=RECORDING_RESOLVE_PRIORITY,
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
        transaction.on_commit(
            lambda: fetch_recording.apply_async(
                args=[str(locked.pk)], priority=RECORDING_FETCH_PRIORITY
            )
        )
    return {"status": "found"}


@shared_task(
    name="calls.fetch_recording",
    bind=True,
    max_retries=5,
    acks_late=True,
    reject_on_worker_lost=True,
    # Intentionally above normal production volume so backlog recovery does
    # not starve fresh recording work.
    rate_limit="20/s",
    priority=RECORDING_FETCH_PRIORITY,
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
    claimable_statuses = [
        CallEvent.Status.PENDING,
        CallEvent.Status.RETRYING,
        CallEvent.Status.FAILED,
    ]
    # With late acknowledgements, Redis redelivers a task after a worker is
    # lost. The previous process may have committed DOWNLOADING immediately
    # before it died, so that redelivery must be allowed to reclaim its own
    # stale state. Ordinary duplicate deliveries remain blocked.
    if (self.request.delivery_info or {}).get("redelivered"):
        claimable_statuses.append(CallEvent.Status.DOWNLOADING)
    claimed = CallEvent.objects.filter(
        pk=event.pk,
        recording_download_status__in=claimable_statuses,
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

    # A task retry or a manually re-queued failed event must never blindly
    # reuse the URL from the previous attempt. Re-resolve it first, because
    # VICIdial recording locations can change after call finalization.
    if self.request.retries > 0 or event.recording_download_status in {
        CallEvent.Status.RETRYING,
        CallEvent.Status.FAILED,
    }:
        refreshed = _refresh_recording_after_failure(event, "retry")
        if refreshed:
            event.recording_source_url = refreshed.location
            event.source_recording_id = (
                refreshed.recording_id or event.source_recording_id
            )

    download_error = None
    try:
        path, size, sha256 = download_recording(
            event.dialer, event.recording_source_url, recording_uuid
        )
    except (ValidationError, SoftTimeLimitExceeded, httpx.HTTPError, OSError) as exc:
        download_error = exc

    # Re-query after every ordinary download failure, not just a 404. A 5xx,
    # timeout, or dropped connection can occur while VICIdial is moving the
    # file to its final location. Soft timeouts defer lookup to the next task
    # attempt so the worker has enough time to shut down cleanly.
    if download_error is not None and not isinstance(
        download_error, SoftTimeLimitExceeded
    ):
        failed_url = event.recording_source_url
        refreshed = _refresh_recording_after_failure(
            event,
            f"download:{_http_status(download_error) or type(download_error).__name__}",
        )
        if refreshed and refreshed.location != event.recording_source_url:
            try:
                path, size, sha256 = download_recording(
                    event.dialer, refreshed.location, recording_uuid
                )
                event.recording_source_url = refreshed.location
                download_error = None
            except (
                ValidationError,
                SoftTimeLimitExceeded,
                httpx.HTTPError,
                OSError,
            ) as exc:
                download_error = exc
                logger.warning(
                    "Download from refreshed recording URL failed",
                    extra={
                        "event_id": event_id,
                        "url_changed": refreshed.location != failed_url,
                        "error": str(exc),
                    },
                )

    if download_error is not None:
        permanent_error = isinstance(download_error, ValidationError)
        final_attempt = self.request.retries >= self.max_retries or permanent_error
        CallEvent.objects.filter(pk=event.pk).update(
            recording_download_status=CallEvent.Status.FAILED
            if final_attempt
            else CallEvent.Status.RETRYING,
            recording_download_last_error=str(download_error)[:1000],
        )
        logger.warning(
            "Recording download failed",
            extra={
                "event_id": event_id,
                "attempt": self.request.retries + 1,
                "status_code": _http_status(download_error),
                "error": str(download_error),
            },
        )
        if final_attempt:
            raise download_error
        raise self.retry(
            exc=download_error,
            countdown=min(120, 2 ** (self.request.retries + 1)),
        )
    measured_duration = recording_duration_seconds(path)
    update_fields = {
        "recording_path": path,
        "recording_size_bytes": size,
        "recording_sha256": sha256,
        "recording_download_status": CallEvent.Status.DOWNLOADED,
        "recording_download_last_error": "",
    }
    if measured_duration is not None:
        update_fields["talk_time"] = measured_duration
    else:
        logger.warning(
            "Recording duration could not be measured; retaining webhook duration",
            extra={"event_id": event_id, "recording_path": path},
        )
    CallEvent.objects.filter(pk=event.pk).update(**update_fields)
    logger.info(
        "Recording downloaded",
        extra={
            "event_id": event_id,
            "recording_uuid": str(recording_uuid),
            "bytes": size,
            "duration_seconds": measured_duration,
        },
    )
    return {"status": "downloaded", "bytes": size}
