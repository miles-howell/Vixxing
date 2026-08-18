import os
from dotenv import load_dotenv
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)

# Baking cookies...
SESSION_COOKIE_NAME = "totp_sessionid"
CSRF_COOKIE_NAME = "totp_csrftoken"
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
#SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


SECRET_KEY = os.getenv('SECRET_KEY')

DEBUG = False

ALLOWED_HOSTS = [os.getenv('ALLOWED_HOSTS')]
#CSRF_TRUSTED_ORIGINS = ['*']

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'verify',
    'msgraphbackend',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'TOTP.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'TOTP.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

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
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# WhiteNoise: compress & cache static files
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration
#
# Enrollment mail is delivered through whichever of these named mailers
# succeeds, tried in this order (see verify/views.py:_delivery_backends):
#   1. 'default' (Microsoft Graph API) - preferred; authenticates with a
#      short-lived OAuth token instead of a standing SMTP password.
#   2. 'smtp' - used automatically as a fallback if Graph delivery fails, or
#      if Graph isn't configured at all.
# The 'smtp' mailer is only defined at all when EMAIL_HOST is set, so
# verify/views.py:_delivery_backends can gate on plain alias membership in
# MAILERS - which also happens to be exactly what Django's test runner
# preserves when it swaps every mailer to an in-memory backend for tests.

MSGRAPH_TENANT_ID = os.getenv('MSGRAPH_TENANT_ID')
MSGRAPH_CLIENT_ID = os.getenv('MSGRAPH_CLIENT_ID')
MSGRAPH_CLIENT_SECRET = os.getenv('MSGRAPH_CLIENT_SECRET')
MSGRAPH_USER_ID = os.getenv('MSGRAPH_USER_ID')

MAILERS = {
    'default': {
        'BACKEND': 'msgraphbackend.MSGraphBackend',
    },
}

if os.getenv('EMAIL_HOST'):
    MAILERS['smtp'] = {
        'BACKEND': 'django.core.mail.backends.smtp.EmailBackend',
        'OPTIONS': {
            'host': os.getenv('EMAIL_HOST'),
            'port': int(os.getenv('EMAIL_PORT', '587')),
            'username': os.getenv('EMAIL_HOST_USER'),
            'password': os.getenv('EMAIL_HOST_PASSWORD'),
            'use_tls': os.getenv('EMAIL_USE_TLS', 'true').lower() == 'true',
            'use_ssl': os.getenv('EMAIL_USE_SSL', 'false').lower() == 'true',
        },
    }

# The default From address for enrollment mail, used by both mailers.
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL')
