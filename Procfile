web: python manage.py migrate && python manage.py collectstatic --noinput && gunicorn chalimobile.wsgi:application --bind 0.0.0.0:$PORT --timeout 120

