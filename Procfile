web: python manage.py migrate && python manage.py collectstatic --noinput && gunicorn chalimobile.wsgi:application --bind 0.0.0.0:$PORT
worker: celery -A chalimobile worker -l info
beat: celery -A chalimobile beat -l info
