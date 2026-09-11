from __future__ import annotations

import hashlib
import ipaddress
import math
import mimetypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from mutagen import File as MutagenFile
from mutagen import MutagenError
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.tenancy.models import Dialer


@dataclass(frozen=True)
class RecordingResult:
    start_time: str
    agent_user: str
    recording_id: str
    lead_id: str
    duration: int | None
    location: str


def event_key(event_type: str, payload: dict) -> str:
    stable = "|".join(
        str(value or "")
        for value in (
            event_type,
            payload.get("call_id"),
            payload.get("uniqueid"),
            payload.get("agent_log_id"),
            payload.get("lead_id"),
            payload.get("disposition") or payload.get("dispo") or payload.get("status"),
            payload.get("recording_id"),
            payload.get("call_date"),
            payload.get("phone_number"),
            payload.get("user"),
        )
    )
    return hashlib.sha256(stable.encode()).hexdigest()


def safe_int(value, default: int = 0) -> int:
    try:
        return max(0, int(value or default))
    except (TypeError, ValueError):
        return default


def parse_call_date(value: str | None):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(value[:19], fmt)
            return timezone.make_aware(parsed, timezone.get_current_timezone())
        except ValueError:
            continue
    return None


def parse_recordings(text: str) -> list[RecordingResult]:
    results = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("ERROR:"):
            continue
        parts = line.split("|")
        if len(parts) < 6 or not "|".join(parts[5:]).strip():
            continue
        try:
            duration = int(parts[4].strip())
        except ValueError:
            duration = None
        results.append(
            RecordingResult(
                parts[0].strip(),
                parts[1].strip(),
                parts[2].strip(),
                parts[3].strip(),
                duration,
                "|".join(parts[5:]).strip(),
            )
        )
    return results


def choose_recording(rows: list[RecordingResult], event) -> RecordingResult | None:
    if event.source_recording_id:
        exact = next(
            (row for row in rows if row.recording_id == event.source_recording_id), None
        )
        if exact:
            return exact
    candidates = [row for row in rows if row.agent_user == event.agent_user] or rows
    if event.call_date:

        def distance(row):
            try:
                candidate = timezone.make_aware(
                    datetime.strptime(row.start_time[:19], "%Y-%m-%d %H:%M:%S"),
                    timezone.get_current_timezone(),
                )
                return abs((candidate - event.call_date).total_seconds())
            except ValueError:
                return float("inf")

        candidates.sort(key=distance)
        return candidates[0] if candidates else None
    return (
        sorted(candidates, key=lambda row: row.start_time)[-1] if candidates else None
    )


def lookup_recording(dialer: Dialer, event) -> RecordingResult | None:
    date = (
        event.call_date.strftime("%Y-%m-%d")
        if event.call_date
        else timezone.localdate().isoformat()
    )
    params = {
        "source": dialer.api_source,
        "user": dialer.api_username,
        "pass": dialer.get_api_password(),
        "function": "recording_lookup",
        "stage": "pipe",
        "header": "NO",
        "duration": "Y",
        "lead_id": event.lead_id,
        "date": date,
    }
    with httpx.Client(
        timeout=dialer.request_timeout_seconds, follow_redirects=True, verify=True
    ) as client:
        response = client.get(dialer.api_url, params=params)
        response.raise_for_status()
    if response.text.strip().startswith("ERROR:"):
        return None
    return choose_recording(parse_recordings(response.text), event)


def validate_recording_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValidationError(
            "Recording URL must be an absolute HTTP or HTTPS URL without embedded credentials."
        )
    hostname = parsed.hostname.lower().rstrip(".")
    try:
        address = ipaddress.ip_address(hostname)
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
        ):
            raise ValidationError(
                "Recording URL may not target a private or reserved address."
            )
    except ValueError:
        pass


def download_recording(
    dialer: Dialer, url: str, recording_uuid
) -> tuple[str, int, str]:
    validate_recording_url(url)
    output_dir = settings.RECORDINGS_ROOT
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    timeout = httpx.Timeout(
        connect=dialer.request_timeout_seconds,
        read=90,
        write=dialer.request_timeout_seconds,
        pool=dialer.request_timeout_seconds,
    )
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        verify=settings.RECORDING_DOWNLOAD_VERIFY_TLS,
    ) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            declared = safe_int(response.headers.get("content-length"))
            if declared > settings.RECORDING_MAX_BYTES:
                raise ValidationError("Recording exceeds the configured maximum size.")
            content_type = (
                response.headers.get("content-type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            suffix = Path(urlparse(url).path).suffix.lower()
            if suffix not in {".mp3", ".wav", ".ogg", ".m4a", ".flac"}:
                suffix = mimetypes.guess_extension(content_type) or ".bin"
            if suffix not in {".mp3", ".wav", ".ogg", ".m4a", ".flac"}:
                raise ValidationError("Unsupported recording media type.")
            final_path = output_dir / f"{recording_uuid}{suffix}"
            temp_path = output_dir / f".{recording_uuid}{suffix}.part"
            try:
                with temp_path.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        total += len(chunk)
                        if total > settings.RECORDING_MAX_BYTES:
                            raise ValidationError(
                                "Recording exceeded the configured maximum size."
                            )
                        digest.update(chunk)
                        handle.write(chunk)
                temp_path.replace(final_path)
            except Exception:
                temp_path.unlink(missing_ok=True)
                raise
    return str(final_path), total, digest.hexdigest()


def recording_duration_seconds(path: str | Path) -> int | None:
    """Read the stored audio's authoritative duration, rounded to a whole second."""
    try:
        media = MutagenFile(str(path))
        length = (
            float(media.info.length)
            if media is not None and media.info is not None
            else float("nan")
        )
    except (AttributeError, MutagenError, OSError, TypeError, ValueError):
        return None
    if not math.isfinite(length) or length < 0:
        return None
    return int(length + 0.5)
