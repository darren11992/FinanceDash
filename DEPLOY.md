# Deploying Penny API to Fly.io

Step-by-step guide to deploy the Penny backend to Fly.io (London region).

## Prerequisites

- [Fly.io account](https://fly.io) (free tier includes 3 shared-cpu-1x VMs)
- Supabase project (production — separate from local dev)
- TrueLayer **live** credentials with redirect URI updated
- Sentry project (optional, free tier)

## 1. Install flyctl

```bash
# macOS
brew install flyctl

# Or via curl
curl -L https://fly.io/install.sh | sh
```

Then authenticate:

```bash
fly auth login
```

## 2. Create the Fly.io app

From the **repo root** (not `backend/`):

```bash
fly apps create penny-api --org personal
```

> If `penny-api` is taken, choose another name and update `app` in
> `backend/fly.toml` to match.

## 3. Set secrets

Secrets are injected as environment variables at runtime. They are
encrypted at rest and never visible in logs or the dashboard.

```bash
fly secrets set \
  SUPABASE_URL="https://your-prod-project.supabase.co" \
  SUPABASE_PUBLISHABLE_KEY="sb_publishable_..." \
  SUPABASE_SECRET_KEY="sb_secret_..." \
  TRUELAYER_CLIENT_ID="your-live-client-id" \
  TRUELAYER_CLIENT_SECRET="your-live-client-secret" \
  TRUELAYER_TOKEN_ENCRYPTION_KEY="your-fernet-key" \
  TRUELAYER_REDIRECT_URI="https://penny-api.fly.dev/api/v1/connections/callback" \
  TRUELAYER_ENV="live" \
  TRUELAYER_AUTH_BASE_URL="https://auth.truelayer.com" \
  TRUELAYER_DATA_BASE_URL="https://api.truelayer.com" \
  APP_ENV="production" \
  APP_DEBUG="false" \
  --app penny-api
```

Optional — add Sentry DSN:

```bash
fly secrets set SENTRY_DSN="https://examplePublicKey@o0.ingest.sentry.io/0" --app penny-api
```

### Important notes on secrets

- **TRUELAYER_TOKEN_ENCRYPTION_KEY**: Use the **same** Fernet key as
  your local dev `.env` if you want to share the same Supabase database.
  Changing the key breaks decryption of existing stored tokens.
- **TRUELAYER_REDIRECT_URI**: Must match exactly what's registered in
  the TrueLayer console (see step 5).
- **CORS_ORIGINS**: Only needed if you serve a Flutter web build from a
  separate domain. Native mobile apps don't need CORS. Leave unset for
  now.

## 4. Deploy

From the **repo root**:

```bash
fly deploy --config backend/fly.toml --dockerfile backend/Dockerfile
```

Fly.io will:
1. Build the Docker image remotely (using the Fly builder)
2. Push it to Fly's internal registry
3. Start a Machine in the `lhr` (London) region
4. Run health checks on `/health`

First deploy takes 2-3 minutes. Subsequent deploys are faster due to
layer caching.

### Verify the deploy

```bash
# Check machine status
fly status --app penny-api

# Hit the health endpoint
curl https://penny-api.fly.dev/health

# View live logs
fly logs --app penny-api
```

Expected health response:

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "environment": "production",
  "truelayer_env": "live",
  "timestamp": "2026-04-08T12:00:00.000000+00:00"
}
```

## 5. Update TrueLayer redirect URI

In the [TrueLayer console](https://console.truelayer.com):

1. Go to your **live** application settings
2. Under **Redirect URIs**, add:
   ```
   https://penny-api.fly.dev/api/v1/connections/callback
   ```
3. Keep the localhost URI for local development
4. Save

> The sandbox application doesn't need updating — it's only used for
> local dev with `uk-cs-mock`.

## 6. Update Flutter app config

Update `mobile/penny/.env` (or create a production variant) to point at
the deployed backend:

```
API_BASE_URL=https://penny-api.fly.dev
```

## Architecture notes

### Single worker

The Dockerfile runs gunicorn with **1 uvicorn worker**. This is
intentional — APScheduler (which runs the 4-hourly sync and daily
consent checker) starts inside the ASGI lifespan. Multiple workers
would create duplicate scheduler instances, causing every job to run
twice.

A single async worker handles concurrent requests via the event loop.
This is more than sufficient for 2-10 users. If you ever need to scale
beyond one Machine, the scheduler should be extracted into a separate
worker process first.

### Machine stays running

`auto_stop_machines = "off"` in `fly.toml` keeps the Machine alive 24/7.
This is required because APScheduler needs a persistent process to fire
scheduled jobs. The cost for a shared-cpu-1x/512MB Machine running 24/7
is approximately **$3.19/month** (within free tier allowances if you
have no other Fly apps).

### Health check

Fly.io pings `GET /health` every 30 seconds. If the endpoint fails to
respond within 5 seconds, Fly marks the Machine as unhealthy and
restarts it after the grace period.

## Common operations

### View logs

```bash
fly logs --app penny-api
```

### SSH into the Machine

```bash
fly ssh console --app penny-api
```

### Restart the app

```bash
fly apps restart penny-api
```

### Update secrets

```bash
fly secrets set KEY="new-value" --app penny-api
# This triggers an automatic redeploy
```

### Check resource usage

```bash
fly machine status --app penny-api
```

### Scale memory (if needed)

Edit `backend/fly.toml`:

```toml
[[vm]]
  size = "shared-cpu-1x"
  memory = "1024mb"
```

Then redeploy: `fly deploy --config backend/fly.toml --dockerfile backend/Dockerfile`

## Rollback

If a deploy breaks something:

```bash
# List recent deployments
fly releases --app penny-api

# Rollback to previous release
fly deploy --image <previous-image-ref> --app penny-api
```

## Cost summary

| Component         | Monthly cost |
|-------------------|-------------|
| Fly.io (1 Machine, shared-cpu-1x/512MB, 24/7) | ~$3.19 (may be covered by free allowance) |
| Supabase Free tier | $0 |
| Sentry Free tier  | $0 |
| **Total**         | **~$0–3.19/month** |
