# database

Generated artifact, as of migration `20240101000003`. This is the complete document; per-object files are under `state/database/`.

## public

### tables

#### accounts

Comment: Billing account. One per paying customer. Users belong to an account.

##### columns

| Column | Type | Nullable | Default | Comment |
| --- | --- | --- | --- | --- |
| `id` | `uuid` | no | `gen_random_uuid()` | UNCOMMENTED |
| `name` | `text` | no | NONE | UNCOMMENTED |
| `status` | `text` | no | `'active'::text` | Lifecycle: active, then suspended, then closed. Only active accounts may create users. See docs/billing/account-lifecycle.md. |
| `created_at` | `timestamp with time zone` | no | `now()` | UNCOMMENTED |

##### primary-key

`id`

##### grants

| Role | Privileges |
| --- | --- |
| `app_user` | SELECT |

#### users

Comment: UNCOMMENTED

##### columns

| Column | Type | Nullable | Default | Comment |
| --- | --- | --- | --- | --- |
| `id` | `uuid` | no | `gen_random_uuid()` | UNCOMMENTED |
| `account_id` | `uuid` | no | NONE | UNCOMMENTED |
| `email` | `text` | no | NONE | UNCOMMENTED |

##### primary-key

`id`

##### foreign-keys

- `account_id` references `public.accounts(id)` on delete CASCADE.

##### row-level-security

Row security is enabled.

##### grants

| Role | Privileges |
| --- | --- |
| `app_user` | SELECT, INSERT |

## extensions

| Extension | Version |
| --- | --- |
| `plpgsql` | 1.0 |

## other-objects

| Kind | Count |
| --- | --- |
| sequences | 0 |
| materialized-views | 0 |
| partitioned-tables | 0 |
| event-triggers | 0 |
| default-privileges | 0 |
