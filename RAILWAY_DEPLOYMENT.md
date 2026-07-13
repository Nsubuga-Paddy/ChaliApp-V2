# Railway Deployment

## Services

Create these Railway services:

1. PostgreSQL
2. Redis
3. Django web service from this `chaliapp` directory
4. Celery worker service from the same repo/directory
5. Celery beat service from the same repo/directory

## Web Start Command

```bash
python manage.py migrate && python manage.py collectstatic --noinput && gunicorn chalimobile.wsgi:application --bind 0.0.0.0:$PORT
```

## Celery Worker Start Command

```bash
celery -A chalimobile worker -l info
```

## Celery Beat Start Command

```bash
celery -A chalimobile beat -l info
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
