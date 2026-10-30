# SALE preset lookup and Project Manager call editor

## Purpose

CallLens enriches newly disposed VICIdial `SALE` calls with the latest transfer preset from VICIdial **User Stats → Manual Outbound Calls**. It also provides a tightly scoped manual editor for explicitly authorized Project Managers.

Historical calls are not backfilled automatically.

## Dialer preset lookup configuration

Open **Administration → Dialers → Edit** and configure the **SALE preset lookup** section:

- **VICIdial User Stats URL** — the complete `user_stats.php` URL, including any provider-specific hidden administration path;
- **Report username** — an account permitted to view User Stats;
- **Report password** — encrypted at rest with the existing `DIALER_CREDENTIAL_KEY`;
- **Verify TLS certificate** — enabled by default; disable only when the provider requires it and the certificate has been independently validated.

The normal non-agent API credentials remain separate from these report credentials.

## Lookup strategy

When a newly ingested call becomes `disposition=SALE`, CallLens queues `calls.resolve_sale_preset`.

The task:

1. requests the dialer's configured `user_stats.php` with HTTP Basic authentication;
2. supplies the call's agent user and the date range covering call start through final disposition;
3. parses the **Manual Outbound Calls for this Time Period** table;
4. considers only rows whose `CALL TYPE` is `XFER_3WAY` and whose `LEAD` equals the CallLens `lead_id`;
5. limits candidates to the call lifecycle window;
6. stores the newest matching row's `PRESET` value in `CallEvent.preset`.

CallLens stores server-side lifecycle bounds in `raw_payload.ingested_started_at` and `raw_payload.ingested_finalized_at` when the same webhook is used for Start Call URL and Dispo Call URL. Preset matching uses those bounds instead of assuming the provider's `SQLdate` has identical semantics at both stages. For final-only calls, `talk_time` and `call_date` provide a conservative lower-bound fallback.

VICIdial report data may lag briefly. Lookup retries after 15, 30, 45 and 60 seconds. If no preset is available after those attempts, CallLens creates a warning notification for every editor-enabled Project Manager mapped to that dialer campaign/project.

The notification links directly to the call editor. If the preset is later populated or the disposition is changed away from `SALE`, the notification is resolved.

## Business fields

`CallEvent` includes:

- `preset` — nullable latest `XFER_3WAY` preset;
- `client_20_plus` — manual boolean indicating at least 20 minutes on the client side;
- `client_30_plus` — manual boolean indicating at least 30 minutes on the client side;
- `client_status` — nullable manual client status;
- `sold` — manual business sale confirmation;
- `stale` — lifecycle flag from Start/Dispo handling.

Rules:

- `client_20_plus`, `client_30_plus`, `sold`, and `preset` are valid only when `disposition=SALE`;
- `client_30_plus=true` always forces `client_20_plus=true`;
- changing a record from `SALE` to another disposition clears `client_20_plus`, `client_30_plus`, `sold`, and `preset`;
- `client_status` is independent and is preserved;
- a VICIdial `SALE` disposition **never** sets `sold=true` automatically.

## Project Manager editor access

A Project Manager must have **Call editor access** enabled by a system administrator. This permission does not broaden data visibility: the editor uses the same `QAProjectAssignment` mappings already used by CallLens, so the PM can edit only calls in their assigned dialer projects.

The workspace is available at `/editor` and supports:

- search by phone, lead ID, call ID, unique ID, agent, disposition, preset or client status;
- disposition filter;
- call date range;
- viewing call identity and project context;
- editing only disposition, 20+, 30+, client status, sold, and preset.

Phone-number-style searches are constrained to records from the previous seven days. Other editor search modes keep their existing behavior, and project assignment checks remain authoritative.

Server-side authorization and validation are authoritative; hiding or modifying browser controls cannot bypass project scope or SALE-only rules. Database constraints also enforce that 20+, 30+, sold, and preset cannot remain populated on a non-SALE call, and 30+ cannot be true unless 20+ is true.

## Migrations

This feature adds:

```text
calls.0020_callevent_client_duration_preset
accounts.0005_user_call_editor_access
tenancy.0009_dialer_preset_lookup_credentials
notifications.0006_add_missing_preset_category
```

Apply all migrations before deploying the new backend/worker/frontend images. Migration `calls.0020` also normalizes any pre-existing non-SALE `sold=true` row back to `false` before installing the SALE-only database constraints.
