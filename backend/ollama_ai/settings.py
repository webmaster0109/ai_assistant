import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse, parse_qsl

import dj_database_url
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-wt7=@yrx1t@e)$d@xd%7!m2@y6kxho(wiz9z+_otsu50fo+1b)'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = [
  '*'
]

LOCAL_DEV_PORTS = (8000, 3000, 4173, 5173, 5174, 5175, 5176, 5177, 5178, 5179)
LOCAL_DEV_ORIGINS = [
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1", "10.47.158.151")
    for port in LOCAL_DEV_PORTS
]
EXTRA_CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
CSRF_TRUSTED_ORIGINS = sorted(set(LOCAL_DEV_ORIGINS + EXTRA_CSRF_TRUSTED_ORIGINS))


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'storages',
    'app',
    # 'sslserver'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    # custom middlewares
    'app.middlewares.constructions.WebsiteUnderConstructionMiddleware',
]

ROOT_URLCONF = 'ollama_ai.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',

                'app.utils.get_website_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'ollama_ai.wsgi.application'

# DB_URL = os.getenv('DATABASE_URL')
# if DB_URL:
#     DATABASES = {
#         'default': dj_database_url.config(
#             default=DB_URL, 
#             conn_max_age=600,
#             ssl_require=True,
#         )
#     }
# else:
#     DATABASES = {
#         'default': {
#             'ENGINE': 'django.db.backends.sqlite3',
#             'NAME': BASE_DIR / 'db.sqlite3',
#         }
#     }

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'khoyrul_db',
#         'USER': 'sanju',
#         'PASSWORD': 'sanjubross@123',
#         'HOST': 'localhost',
#         'PORT': '5432',
#     }
# }

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'OPTIONS': {
            'sslmode': os.getenv('SSL_MODE', 'require'),
        },
    }
}

# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Kolkata'

USE_I18N = True

USE_TZ = True

if os.getenv("REDIS_URL"):
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": os.getenv("REDIS_URL"),
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "SOCKET_CONNECT_TIMEOUT": 5,
                "SOCKET_TIMEOUT": 5,
            }
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "ollama-ai-local-cache",
        }
    }

# CACHES = {
#     'default': {
#         'BACKEND': 'django_redis.cache.RedisCache',
#         'LOCATION': os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/1'),
#         'OPTIONS': {
#             'CLIENT_CLASS': 'django_redis.client.DefaultClient',
#         }
#     }
# }


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATIC_URL = '/static/'

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

DEFAULT_MEDIA_ROOT = os.path.join(BASE_DIR, "public/static")
SERVERLESS_MEDIA_ROOT = os.path.join(tempfile.gettempdir(), "ollama_ai_media")
USE_SERVERLESS_MEDIA_ROOT = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
MEDIA_ROOT = os.getenv("MEDIA_ROOT") or (SERVERLESS_MEDIA_ROOT if USE_SERVERLESS_MEDIA_ROOT else DEFAULT_MEDIA_ROOT)
MEDIA_URL = '/media/'


def normalize_r2_endpoint_url(endpoint_url, bucket_name):
    if not endpoint_url:
        return ""

    parsed = urlparse(endpoint_url.strip())
    if not parsed.scheme or not parsed.netloc:
        return endpoint_url.strip().rstrip("/")

    normalized_path = parsed.path.rstrip("/")
    bucket_segment = f"/{bucket_name}".rstrip("/") if bucket_name else ""
    if bucket_segment and normalized_path.endswith(bucket_segment):
        normalized_path = normalized_path[: -len(bucket_segment)]

    return f"{parsed.scheme}://{parsed.netloc}{normalized_path}".rstrip("/")


R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "").strip()
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
R2_ENDPOINT_URL = normalize_r2_endpoint_url(os.getenv("R2_ENDPOINT_URL", "").strip(), R2_BUCKET_NAME)
R2_PUBLIC_MEDIA_DOMAIN = os.getenv("R2_PUBLIC_MEDIA_DOMAIN", "").strip()
R2_MEDIA_LOCATION = os.getenv("R2_MEDIA_LOCATION", "media").strip("/")
USE_CLOUDFLARE_R2 = all([R2_BUCKET_NAME, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL])

if USE_CLOUDFLARE_R2:
    AWS_ACCESS_KEY_ID = R2_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY = R2_SECRET_ACCESS_KEY
    AWS_STORAGE_BUCKET_NAME = R2_BUCKET_NAME
    AWS_S3_ENDPOINT_URL = R2_ENDPOINT_URL
    AWS_S3_REGION_NAME = os.getenv("R2_REGION", "auto")
    AWS_S3_SIGNATURE_VERSION = "s3v4"
    AWS_S3_ADDRESSING_STYLE = "path"
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = True
    AWS_S3_FILE_OVERWRITE = False
    DEFAULT_FILE_STORAGE = "app.storage_backends.CloudflareR2MediaStorage"

    STORAGES = {
        "default": {
            "BACKEND": "app.storage_backends.CloudflareR2MediaStorage",
            "OPTIONS": {
                "access_key": AWS_ACCESS_KEY_ID,
                "secret_key": AWS_SECRET_ACCESS_KEY,
                "bucket_name": AWS_STORAGE_BUCKET_NAME,
                "endpoint_url": AWS_S3_ENDPOINT_URL,
                "region_name": AWS_S3_REGION_NAME,
                "signature_version": AWS_S3_SIGNATURE_VERSION,
                "addressing_style": AWS_S3_ADDRESSING_STYLE,
                "default_acl": AWS_DEFAULT_ACL,
                "querystring_auth": AWS_QUERYSTRING_AUTH,
                "file_overwrite": AWS_S3_FILE_OVERWRITE,
            },
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
    MEDIA_URL = (
        R2_PUBLIC_MEDIA_DOMAIN.rstrip("/") + "/"
        if R2_PUBLIC_MEDIA_DOMAIN
        else f"{AWS_S3_ENDPOINT_URL.rstrip('/')}/{AWS_STORAGE_BUCKET_NAME}/{R2_MEDIA_LOCATION}/"
    )
