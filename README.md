# QA Portal

A containerized, multi-tenant quality assurance portal for VICIdial call intake, recording retrieval, review workflows, and operational insight.

## Architecture

- **Django 5.2 LTS + Django REST Framework** for the domain, administration, and session-secured API
- **Django Channels + Redis** for authenticated branch-scoped real-time notifications
- **Celery + Redis** for durable, retryable VICIdial recording lookup and downloads
- **PostgreSQL** for companies, branches, users, dialers, calls, reviews, and audit events
- **React 19 + Ant Design 6** for the responsive portal interface
- **Nginx** for same-origin SPA, API, admin, and WebSocket routing

## First run

```bash
make setup
```

Open `.env` and replace the database, Django, and administrator passwords. Generate the dialer encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put its output in `DIALER_CREDENTIAL_KEY`, then start everything:

```bash
make up
docker compose logs -f backend worker
```

Open <http://localhost:8080>. The initial administrator comes from `ADMIN_EMAIL` and `ADMIN_PASSWORD`; it is created once and is not overwritten on later boots.

## Development tunnel

When `PRODUCTION=false`, Docker Compose starts a Cloudflare Quick Tunnel for testing VICIdial callbacks against a development machine. After the tunnel connects, its temporary public URL is written to:

```text
runtime/cloudflared-url.txt
```

Read it after startup with:

```bash
cat runtime/cloudflared-url.txt
```

The URL changes whenever the tunnel container is recreated. Quick Tunnels are intended only for development and testing. Set `PRODUCTION=true` for a production deployment; this forces Django debug mode off and HTTPS redirects on, the Cloudflare sidecar exits without opening a tunnel, and no `trycloudflare.com` host is trusted by Django.

## Configure a company and VICIdial

1. Sign into `/admin` with the system administrator to use the Ant Design administration workspace. The low-level Django fallback is available at `/django-admin/`.
2. Create a company, then a branch under it.
3. Create portal users and assign each one company, branch, and role.
4. Create a dialer under the branch. Enter its non-agent API URL/user/password, a long webhook secret, and any separate recording hostnames in the allowlist.
5. Copy the dialer's UUID shown in the admin URL.

Use this VICIdial Dispo Call URL (replace the host, UUID, and secret):

```text
VARhttps://YOUR-PORTAL/api/v1/webhooks/vicidial/DIALER_UUID/dispo/?token=WEBHOOK_SECRET&lead_id=--A--lead_id--B--&call_id=--A--call_id--B--&uniqueid=--A--uniqueid--B--&agent_log_id=--A--agent_log_id--B--&user=--A--user--B--&campaign=--A--campaign--B--&phone_number=--A--phone_number--B--&list_id=--A--list_id--B--&dispo=--A--dispo--B--&talk_time=--A--talk_time--B--&term_reason=--A--term_reason--B--&recording_id=--A--recording_id--B--&recording_filename=--A--recording_filename--B--&call_date=--A--SQLdate--B--
```

The endpoint responds immediately after the call is stored. A Celery worker performs recording lookup and download with bounded exponential retries. Duplicate webhooks are idempotent.

## Security baseline

- Passwords use Argon2 and Django's password validation.
- Authentication uses HTTP-only server sessions; no access token is stored in browser JavaScript.
- State-changing requests require CSRF tokens.
- Five failed sign-ins lock that email/IP pair for one hour.
- Every non-administrator user is constrained to one company and one branch.
- API querysets and WebSocket groups enforce branch scope on the server.
- Webhook secrets are one-way hashed; dialer API passwords are Fernet-encrypted at rest.
- Recording downloads require HTTPS, an explicit host allowlist, supported audio types, and a size cap.
- Login, logout, failures, and password reset operations are audited.

For public deployment, set `PRODUCTION=true`, configure trusted HTTPS origins/hosts, terminate TLS at the load balancer, use managed secrets, configure SMTP, and rotate the bootstrap administrator password out of the environment after first use. Production mode forces debug off and HTTPS redirects on; the edge proxy must preserve `X-Forwarded-Proto: https`.

## Checks

```bash
make test
docker compose config
```
