from pathlib import Path
import os
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

IS_RAILWAY = bool(os.getenv('RAILWAY_ENVIRONMENT') or os.getenv('RAILWAY_PROJECT_ID'))
DJANGO_ENV = os.getenv('DJANGO_ENV', 'production' if IS_RAILWAY else 'development').lower()

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if DJANGO_ENV == 'production':
        raise ImproperlyConfigured('DJANGO_SECRET_KEY не установлен!')
    SECRET_KEY = 'django-insecure-dev-only-change-in-production'

DEBUG = os.getenv(
    'DJANGO_DEBUG',
    'True' if DJANGO_ENV != 'production' else 'False',
).lower() in ('true', '1', 'yes', 'on')

_allowed_hosts_env = os.getenv('DJANGO_ALLOWED_HOSTS', '')
ALLOWED_HOSTS = [host.strip() for host in _allowed_hosts_env.split(',') if host.strip()]

if IS_RAILWAY:
    railway_public_domain = (os.getenv('RAILWAY_PUBLIC_DOMAIN') or '').strip()
    if railway_public_domain:
        ALLOWED_HOSTS.append(railway_public_domain)
    # Railway preview/production domains
    ALLOWED_HOSTS.append('.up.railway.app')

ALLOWED_HOSTS = list(dict.fromkeys(ALLOWED_HOSTS))
if DEBUG:
    ALLOWED_HOSTS.extend(['localhost', '127.0.0.1', '[::1]', '0.0.0.0'])
elif not ALLOWED_HOSTS:
    raise ImproperlyConfigured('DJANGO_ALLOWED_HOSTS должен быть установлен в продакшене!')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'warehouse.apps.WarehouseConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'warehouse.middleware.DatabaseUnavailableMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

try:
    import whitenoise  # noqa: F401
except ImportError:
    WHITENOISE_AVAILABLE = False
else:
    WHITENOISE_AVAILABLE = True
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

ROOT_URLCONF = 'tehsnab_warehouse.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'warehouse.context_processors.company_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'tehsnab_warehouse.wsgi.application'
ASGI_APPLICATION = 'tehsnab_warehouse.asgi.application'

DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
DB_ENGINE = os.getenv('DB_ENGINE', '').strip()
DB_CONN_MAX_AGE = 0 if DEBUG else int(os.getenv('DB_CONN_MAX_AGE', '600'))
DB_CONN_HEALTH_CHECKS = os.getenv('DB_CONN_HEALTH_CHECKS', 'True').lower() in ('true', '1', 'yes', 'on')
DB_CONNECT_TIMEOUT = int(os.getenv('DB_CONNECT_TIMEOUT', '3'))

if DATABASE_URL:
    db_config = dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=DB_CONN_MAX_AGE,
        ssl_require=os.getenv('DB_SSL_REQUIRE', 'False').lower() == 'true',
    )
    db_config['CONN_HEALTH_CHECKS'] = DB_CONN_HEALTH_CHECKS
    db_config.setdefault('OPTIONS', {})['connect_timeout'] = DB_CONNECT_TIMEOUT
    DATABASES = {
        'default': db_config
    }
elif DB_ENGINE:
    if DB_ENGINE == 'django.db.backends.sqlite3':
        db_name = os.getenv('DB_NAME') or str(BASE_DIR / 'db.sqlite3')
    else:
        db_name = os.getenv('DB_NAME', '')
        if not db_name:
            raise ImproperlyConfigured('Для PostgreSQL укажите DB_NAME в .env')

    DATABASES = {
        'default': {
            'ENGINE': DB_ENGINE,
            'NAME': db_name,
            'USER': os.getenv('DB_USER', ''),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', ''),
            'PORT': os.getenv('DB_PORT', ''),
            'CONN_MAX_AGE': DB_CONN_MAX_AGE,
            'CONN_HEALTH_CHECKS': DB_CONN_HEALTH_CHECKS,
            'OPTIONS': {'connect_timeout': DB_CONNECT_TIMEOUT},
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True
USE_TZ = True

DATE_FORMAT = 'd.m.Y'
DATETIME_FORMAT = 'd.m.Y H:i'
DECIMAL_SEPARATOR = ','
THOUSAND_SEPARATOR = ' '
USE_THOUSAND_SEPARATOR = True

STATIC_URL = '/static/'
warehouse_static = BASE_DIR / 'warehouse' / 'static'
STATICFILES_DIRS = [warehouse_static] if warehouse_static.exists() else []
STATIC_ROOT = BASE_DIR / 'staticfiles'
if WHITENOISE_AVAILABLE:
    STORAGES = {
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
    }

_csrf_trusted_origins_env = os.getenv('CSRF_TRUSTED_ORIGINS', '')
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in _csrf_trusted_origins_env.split(',') if origin.strip()]

if IS_RAILWAY:
    railway_public_domain = (os.getenv('RAILWAY_PUBLIC_DOMAIN') or '').strip()
    if railway_public_domain:
        CSRF_TRUSTED_ORIGINS.append(f'https://{railway_public_domain}')

CSRF_TRUSTED_ORIGINS = list(dict.fromkeys(CSRF_TRUSTED_ORIGINS))

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'

LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(exist_ok=True)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
        'custom': {
            'format': '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
            'datefmt': '%d.%m.%Y %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'custom',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': LOGS_DIR / 'django.log',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'warehouse': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')

COMPANY_NAME = 'Татнефтеснаб'
COMPANY_FULL_NAME = 'Управление «Татнефтеснаб» ПАО «ТАТНЕФТЬ» им. В.Д. Шашина'
COMPANY_INN = '1645001234'
COMPANY_KPP = '164501001'
COMPANY_OGRN = '1021602840'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SESSION_COOKIE_AGE = 3600
SESSION_SAVE_EVERY_REQUEST = False
