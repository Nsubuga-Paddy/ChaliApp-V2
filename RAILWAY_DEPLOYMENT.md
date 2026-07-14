# Railway Deployment

## Services

Create these Railway services from the same `chaliapp` directory:

1. PostgreSQL
2. Redis
3. Django web service
4. Celery worker service
5. Celery beat service

## Start commands (`railway.json`)

`railway.json` uses one shared start command that switches on `SERVICE_ROLE`:

| Service | `SERVICE_ROLE` value | Process started |
|---|---|---|
| Web | unset or `web` | migrate + collectstatic + gunicorn |
| Celery worker | `worker` | `celery -A chalimobile worker -l info` |
| Celery beat | `beat` | `celery -A chalimobile beat -l info` |

Set these **Variables** on each service:

- Web: `SERVICE_ROLE=web` (or leave unset)
- Celery worker: `SERVICE_ROLE=worker`
- Celery beat: `SERVICE_ROLE=beat`

Then redeploy. Worker/beat logs must show Celery, not gunicorn.

Equivalent Procfile process types (for reference):

```bash
web: python manage.py migrate && python manage.py collectstatic --noinput && gunicorn chalimobile.wsgi:application --bind 0.0.0.0:$PORT --timeout 120
worker: celery -A chalimobile worker -l info
beat: celery -A chalimobile beat -l info
```

## Required Variables

Set these on the Django web, worker, and beat services:

```env
DEBUG=False
SECRET_KEY=replace-with-a-long-random-secret
OPENAI_API_KEY=your-openai-api-key
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
CELERY_BROKER_URL=${{Redis.REDIS_URL}}
CELERY_RESULT_BACKEND=${{Redis.REDIS_URL}}
```

Plus the role variable above:

```env
# web service
SERVICE_ROLE=web

# worker service
SERVICE_ROLE=worker

# beat service
SERVICE_ROLE=beat
```

Set this after Railway gives you the public domain:

```env
ALLOWED_HOSTS=your-app.up.railway.app
CORS_ALLOWED_ORIGINS=https://your-app.up.railway.app
CSRF_TRUSTED_ORIGINS=https://your-app.up.railway.app
```

Railway also provides `RAILWAY_PUBLIC_DOMAIN`. The settings file will add it to
`ALLOWED_HOSTS`, CORS, and CSRF origins automatically when present.

## Media Files

For uploaded company logos and knowledge documents, add a Railway volume and set:

```env
MEDIA_ROOT=/data/media
SERVE_MEDIA=True
```

This is acceptable for an early deployment. For larger production use, move media
to object storage such as S3, Cloudinary, or DigitalOcean Spaces.

## Flutter API URL

Build or run the mobile app with the Railway HTTPS URL:

```powershell
flutter run --dart-define=API_BASE_URL=https://your-app.up.railway.app
```

```powershell
flutter build apk --dart-define=API_BASE_URL=https://your-app.up.railway.app
```
