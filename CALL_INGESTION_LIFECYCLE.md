# VICIdial call ingestion lifecycle

CallLens uses one canonical `CallEvent` row for the full VICIdial call lifecycle. The **same webhook URL is configured in both VICIdial Start Call URL and Dispo Call URL**.

## Webhook

```text
VARhttps://YOUR-PORTAL/api/v1/webhooks/vicidial/DIALER_UUID/dispo/?token=WEBHOOK_SECRET&lead_id=--A--lead_id--B--&call_id=--A--call_id--B--&uniqueid=--A--uniqueid--B--&closecallid=--A--closecallid--B--&xfercallid=--A--xfercallid--B--&agent_log_id=--A--agent_log_id--B--&user=--A--user--B--&agent_full_name=--A--fullname--B--&campaign=--A--campaign--B--&group=--A--group--B--&did_id=--A--did_id--B--&did_pattern=--A--did_pattern--B--&dialed_number=--A--dialed_number--B--&dialed_label=--A--dialed_label--B--&entry_list_id=--A--entry_list_id--B--&phone_number=--A--phone_number--B--&list_id=--A--list_id--B--&dispo=--A--dispo--B--&talk_time=--A--talk_time--B--&term_reason=--A--term_reason--B--&recording_id=--A--recording_id--B--&recording_filename=--A--recording_filename--B--&call_date=--A--SQLdate--B--
```

Do not store a real production webhook secret in documentation or source control.

## Start Call URL behavior

A Start Call callback is treated as provisional when `dispo` is `NEW`, blank, the unsubstituted placeholder `--A--dispo--B--`, or legacy `INCALL`. CallLens normalizes new provisional callbacks to the canonical stored disposition `NEW`. Existing legacy `INCALL` rows remain supported for safe upgrades.

The call is inserted into the normal call library immediately, but the backend deliberately does **not** start:

- VICIdial recording lookup;
- recording download;
- QA reservation/evaluation;
- other post-disposition processing.

The existing recording status fields remain pending until a real disposition arrives or the call becomes stale.

## Final disposition behavior

A later real disposition callback on the same webhook updates the existing provisional `NEW` (or legacy `INCALL`) row instead of inserting a second call.

Matching is performed in this order:

1. `uniqueid`;
2. `call_id`;
3. `agent_log_id`;
4. bounded fallback of `lead_id + agent user` within the previous 12 hours.

On finalization CallLens refreshes dialer-owned metadata, clears `stale`, resets recording state to pending if necessary, then starts the existing asynchronous recording pipeline and normal QA eligibility flow. The original Start Call timestamp is preserved when available, while server-side `ingested_started_at` / `ingested_finalized_at` lifecycle bounds are retained in the raw payload for preset correlation. A duplicate final webhook does not queue the pipeline twice.

## Stale calls

Celery Beat runs `calls.mark_stale_calls` every 60 seconds. Any provisional `NEW` row (and any legacy `INCALL` row) whose `received_at` is at least two hours old is changed to:

```text
disposition = STALE
stale = true
```

Recording lookup/download are marked `SKIPPED`. Stale calls remain visible in Call Logs but are explicitly rejected by the QA analysis endpoint.

A late real disposition can recover a stale call. Recovery also matches rows whose `stale=true` even if a Project Manager has already manually changed their displayed disposition. The same row is updated, `stale` becomes `false`, and normal recording/QA processing begins. A late non-SALE disposition clears SALE-only business fields but preserves `client_status`.

## Business fields

`CallEvent` includes:

- `client_status`: nullable string, initially `NULL`;
- `sold`: boolean, default `false`;
- `client_20_plus`: manual client-side 20+ minute flag;
- `client_30_plus`: manual client-side 30+ minute flag;
- `preset`: nullable latest VICIdial `XFER_3WAY` preset;
- `stale`: boolean, default `false`.

`client_status` and `sold` are business-managed fields and are intentionally independent from VICIdial disposition. In particular, `disposition=SALE` **does not** automatically set `sold=true`. Late dialer dispositions preserve existing business values. SALE-only editor validation, automatic preset lookup, and Project Manager editor access are documented in [`CALL_EDITOR_AND_PRESET_LOOKUP.md`](CALL_EDITOR_AND_PRESET_LOOKUP.md).

VICIdial sale aliases `SQSAL` and `SMSAL` are normalized to canonical `SALE` as soon as the Dispo callback is parsed. They therefore use the same finalization, recording lookup, preset lookup, notifications, editor rules, and analytics flow as a normal `SALE` callback. The original raw `dispo` value remains in `raw_payload` for auditability.

## Migration and services

Lifecycle migration:

```text
calls.0019_callevent_stale_client_status_sold
```

Additional SALE/editor migrations:

```text
calls.0020_callevent_client_duration_preset
accounts.0005_user_call_editor_access
tenancy.0009_dialer_preset_lookup_credentials
notifications.0006_add_missing_preset_category
```

A Celery Beat service is included in `compose.yml`. Production must run `backend`, `worker`, `beat`, and `frontend` after deployment.

Typical deployment sequence:

```bash
docker compose build backend worker beat frontend
docker compose run --rm --no-deps -e DB_DIRECT=true --entrypoint python backend manage.py migrate --noinput
docker compose up -d --no-deps --wait backend
docker compose up -d --no-deps worker beat
docker compose up -d --no-deps --wait frontend
```

Verify the scheduler and worker:

```bash
docker compose ps backend worker beat
docker compose logs --tail=100 beat worker backend
```

## Clean rollback

Back up PostgreSQL first. If this complete lifecycle/editor feature set must be removed, reverse its migrations while this code version is still present, then deploy the older code:

```bash
docker compose stop beat worker backend
docker compose run --rm --no-deps -e DB_DIRECT=true --entrypoint python backend manage.py migrate calls 0018 --noinput
docker compose run --rm --no-deps -e DB_DIRECT=true --entrypoint python backend manage.py migrate accounts 0004 --noinput
docker compose run --rm --no-deps -e DB_DIRECT=true --entrypoint python backend manage.py migrate tenancy 0008 --noinput
docker compose run --rm --no-deps -e DB_DIRECT=true --entrypoint python backend manage.py migrate notifications 0005 --noinput
# deploy/rebuild the older code only after the migrations have been reversed
```

The calls rollback removes the client-duration/preset fields first and then the stale/client-status/sold lifecycle fields. Do not remove migration files before reversing them.

## Lifecycle timestamp and idempotency integrity

CallLens deliberately separates the first callback receipt from final-disposition receipt.

- `received_at` is immutable and records when the lifecycle row was first created (normally the Start Call callback).
- `finalized_at` records the first authoritative non-provisional disposition callback.
- API/UI `received_at` presentation uses `finalized_at` when present, otherwise the first receipt. The original value remains available as `first_received_at`.
- stale detection continues to use the immutable first receipt, so a callback retry cannot extend the two-hour stale window.
- the webhook idempotency key is based on stable VICIdial identifiers (`call_id`, then `agent_log_id`, then `uniqueid`) and does not include mutable disposition, SQLdate, recording ID, or talk time.
- duplicate/corrected final callbacks therefore update the same lifecycle row and do not enqueue duplicate recording/QA work.
- legacy rows created with the older event-key scheme remain compatible because the webhook also reconciles by strong VICIdial identifiers.

For VICIdial configuration, configure the Start Call URL with a literal `dispo=NEW`. Keep the final Dispo Call URL dynamic with `dispo=--A--dispo--B--`. Do not use the static Start Call URL in the final-disposition field.
