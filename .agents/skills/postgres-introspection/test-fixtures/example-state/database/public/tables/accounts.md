# public.tables.accounts

Generated artifact, as of migration `20240101000003`. Part of `state/database`; the complete document is `state/database.md`.

Comment: Billing account. One per paying customer. Users belong to an account.

## columns

| Column | Type | Nullable | Default | Comment |
| --- | --- | --- | --- | --- |
| `id` | `uuid` | no | `gen_random_uuid()` | UNCOMMENTED |
| `name` | `text` | no | NONE | UNCOMMENTED |
| `status` | `text` | no | `'active'::text` | Lifecycle: active, then suspended, then closed. Only active accounts may create users. See docs/billing/account-lifecycle.md. |
| `created_at` | `timestamp with time zone` | no | `now()` | UNCOMMENTED |

## primary-key

`id`

## foreign-keys

NONE

## indexes

- `accounts_pkey`: `CREATE UNIQUE INDEX accounts_pkey ON public.accounts USING btree (id)`

## row-level-security

Row security is not enabled.

## grants

| Role | Privileges |
| --- | --- |
| `app_user` | SELECT |
