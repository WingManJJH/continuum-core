# Multi-user Continuum

The same five apps (governance, dashboard, canvas, advisor, ask) serve many people at once. Each person signs in, works in the models they have been given, and every change they make is recorded under their name and role.

## Run it

```bash
# 1. storage: Postgres for a shared deployment (docs/postgres.md); files also work for a pilot
export CONTINUUM_DATABASE_URL=postgresql://continuum_app:…@db:5432/continuum
python db/migrate.py

# 2. sign-in: Microsoft Entra ID (any OpenID Connect provider works the same way)
export CONTINUUM_AUTH=oidc
export CONTINUUM_OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0
export CONTINUUM_OIDC_CLIENT_ID=<application (client) id>
export CONTINUUM_OIDC_CLIENT_SECRET=<client secret>
export CONTINUUM_OIDC_ALLOWED_DOMAINS=yourcompany.com           # optional
export CONTINUUM_PUBLIC_URL=https://continuum.yourcompany.com     # redirect URI = <this>/auth/callback (default http://localhost:8080)
export CONTINUUM_SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
export CONTINUUM_ADMIN_EMAILS=you@yourcompany.com                 # organization admins
export CONTINUUM_HOST=0.0.0.0                                     # behind your TLS reverse proxy

python run.py                     # one address: http://localhost:8080 (canvas /, /governance/, /dashboard/, /advisor/, /ask/)
```

All five apps are served from **one address** by `web/gateway.py`. That means one sign-in, one TLS certificate, one reverse-proxy rule, and one Entra redirect URI. Use `python run.py --separate` if you need the original five ports.

For local testing with several people, use `CONTINUUM_AUTH=dev`. You type an email to sign in, and nothing else changes.

`CONTINUUM_AUTH=off`, the default, keeps the original single-user behaviour.

**Entra ID app registration:**

- Platform: Web.
- Redirect URI: `<CONTINUUM_PUBLIC_URL>/auth/callback`.
- ID tokens: on.
- API permissions: `openid`, `email`, `profile`.

## Who can do what (per model)

| Role | Can |
|---|---|
| viewer | Read everything: maps, strategy, Enterprise modules, history, audit |
| editor | Change the model: processes, steps, guardrails, capabilities, applications, obligations, controls, risks |
| approver | Everything an editor can, plus decide change requests and staged import changes |
| admin | Everything, plus members and access, approval policy, imports and reverting imports |

The first person to sign in to an empty system, or anyone listed in `CONTINUUM_ADMIN_EMAILS`, is an organization admin. An organization admin is admin of every model.

Admins give people access in the canvas: click your name, then **Members & access**. A person can be linked to one of the model's roles, for example `role.qms.iso_advisor`. That role is then recorded as the actor on their changes, so RACI, approvals and audit name a real, accountable role (ISO 9001 §5.3).

## What is guaranteed

- **Identity comes only from the session.** The apps ignore any `actor` or `reviewer` the browser sends.
- **Every change records who made it.** The person's role and their email are written to the hash-chained change log.
- **Each person works in their own model.** One person switching models never moves anyone else.
- **Saves never collide silently.** If two people save the same record at once, one is saved; the other gets "someone saved this first" and sees the latest version.
- **Live updates.** Everyone sees changes as they happen.
- **Imports never overwrite a record edited in Continuum.** The incoming version waits under **Imports** for an approver to accept or reject it (D51).
- **Sessions are protected.**
  - The session is a signed, HttpOnly, SameSite cookie that expires after 12 hours by default.
  - An admin can sign a person out everywhere.
  - Sign-ins and access changes are kept in their own chained log.
- **Cross-site write protection.** Writes must be JSON from the same origin.

## Where things are in the canvas

| Area | What it shows |
|---|---|
| **Enterprise** | **Atlas**, the capability map. Each capability shows its processes and systems, roll-up maturity and overlap |
| | **Applications & agents** |
| | **Obligations (Assure)**: the ISO 9001 / ISO 9004 clause matrix, with one-click mapping |
| | **Risks & controls**: the risk heat map and control test records |
| | **Vitals**: the model-health score and findings |
| | Click any item to see its **Ripple**: what a change to it reaches |
| **Imports** | Import batches, changes waiting for review with a field-by-field diff, accept / keep ours, and revert a batch |
