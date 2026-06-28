"""
Django settings for chalimobile project.
"""

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ('true', '1', 'yes', 'on')


def env_list(name: str, default: str = '') -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-dev-key-change-me')
DEBUG = env_bool('DEBUG', True)
RAILWAY_PUBLIC_DOMAIN = os.getenv('RAILWAY_PUBLIC_DOMAIN', '').strip()
ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', 'localhost,127.0.0.1')
if RAILWAY_PUBLIC_DOMAIN and RAILWAY_PUBLIC_DOMAIN not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RAILWAY_PUBLIC_DOMAIN)

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_EMBEDDING_MODEL = os.getenv('OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small')
KNOWLEDGE_WEB_TIMEOUT_SECONDS = int(os.getenv('KNOWLEDGE_WEB_TIMEOUT_SECONDS', '20'))
KNOWLEDGE_WEB_REQUEST_DELAY_SECONDS = float(os.getenv('KNOWLEDGE_WEB_REQUEST_DELAY_SECONDS', '0.5'))
KNOWLEDGE_WEB_MAX_PAGES_CAP = int(os.getenv('KNOWLEDGE_WEB_MAX_PAGES_CAP', '50'))
KNOWLEDGE_WEB_MAX_DEPTH_CAP = int(os.getenv('KNOWLEDGE_WEB_MAX_DEPTH_CAP', '2'))
KNOWLEDGE_WEB_USER_AGENT = os.getenv(
    'KNOWLEDGE_WEB_USER_AGENT',
    'ChaliKnowledgeCrawler/1.0 (+company-approved-knowledge-refresh)',
)

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'django_filters',
    'django_celery_beat',
    # Chali apps
    'accounts',
    'tenants',
    'operations',
    'payments',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'tenants.middleware.CompanyContextMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'chalimobile.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'chalimobile.wsgi.application'
ASGI_APPLICATION = 'chalimobile.asgi.application'

DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=not DEBUG,
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_USER_MODEL = 'accounts.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = Path(os.getenv('MEDIA_ROOT', BASE_DIR / 'media'))
SERVE_MEDIA = env_bool('SERVE_MEDIA', DEBUG)

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'tenants.pagination.StandardPagination',
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=12),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
}

CORS_ALLOWED_ORIGINS = env_list('CORS_ALLOWED_ORIGINS', 'http://localhost:3000')
if RAILWAY_PUBLIC_DOMAIN:
    railway_origin = f'https://{RAILWAY_PUBLIC_DOMAIN}'
    if railway_origin not in CORS_ALLOWED_ORIGINS:
        CORS_ALLOWED_ORIGINS.append(railway_origin)
CORS_ALLOW_HEADERS = (
    'accept',
    'authorization',
    'content-type',
    'origin',
    'x-company-id',
)

CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')
if not CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS

USE_X_FORWARDED_HOST = env_bool('USE_X_FORWARDED_HOST', not DEBUG)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', not DEBUG)
SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', not DEBUG)
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '0' if DEBUG else '31536000'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', not DEBUG)
SECURE_HSTS_PRELOAD = env_bool('SECURE_HSTS_PRELOAD', False)

# ── Pegasus payment gateway ───────────────────────────────────────────────────
PEGASUS_BASE_URL = os.getenv('PEGASUS_BASE_URL', 'https://sandbox.pegasusgateway.com')
PEGASUS_USERNAME = os.getenv('PEGASUS_USERNAME', '')
PEGASUS_PASSWORD = os.getenv('PEGASUS_PASSWORD', '')
PEGASUS_VENDOR_CODE = os.getenv('PEGASUS_VENDOR_CODE', '')
PEGASUS_TIMEOUT = int(os.getenv('PEGASUS_TIMEOUT', '30'))
# Biller codes — override per environment
PEGASUS_BILLER_YAKA = os.getenv('PEGASUS_BILLER_YAKA', 'YAKA')
PEGASUS_BILLER_WATER = os.getenv('PEGASUS_BILLER_WATER', 'NWSC')
PEGASUS_BILLER_AIRTIME_MTN = os.getenv('PEGASUS_BILLER_AIRTIME_MTN', 'MTNAIRTIME')
PEGASUS_BILLER_AIRTIME_AIRTEL = os.getenv('PEGASUS_BILLER_AIRTIME_AIRTEL', 'AIRTELAIRTIME')
PEGASUS_BILLER_TV = os.getenv('PEGASUS_BILLER_TV', 'DSTV')
PEGASUS_BILLER_SCHOOL = os.getenv('PEGASUS_BILLER_SCHOOL', 'SCHOOLFEES')
PEGASUS_BILLER_URA = os.getenv('PEGASUS_BILLER_URA', 'URA')

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', CELERY_BROKER_URL)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_BEAT_SCHEDULE = {
    'refresh-due-knowledge-web-sources': {
        'task': 'tenants.tasks.refresh_due_knowledge_web_sources',
        'schedule': 300.0,
    },
}
