from pathlib import Path
from decouple import config, Csv
import os

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY')

# ── Environment ───────────────────────────────────────────────────────────────
DJANGO_ENV   = config('DJANGO_ENV', default='development')
IS_PRODUCTION = DJANGO_ENV == 'production'

DEBUG = not IS_PRODUCTION

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# ── Applications ──────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'accounts',
    'orders',
    'payments',
    'services',
    'support',
    'rest_framework',
    'corsheaders',
]

# ── Middleware ────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

ROOT_URLCONF = 'main.urls'

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
                'support.context_processors.ticket_notifications',
            ],
        },
    },
]

WSGI_APPLICATION = 'main.wsgi.application'

# ── Database ──────────────────────────────────────────────────────────────────
if IS_PRODUCTION:
    import dj_database_url
    DATABASES = {
        'default': dj_database_url.parse(
            config('DATABASE_URL'),
            conn_max_age=600,
            ssl_require=True,
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ── Password validation ───────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ── Internationalisation ──────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'UTC'
USE_I18N      = True
USE_TZ        = True

# ── Static files ──────────────────────────────────────────────────────────────
STATIC_URL  = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

if IS_PRODUCTION:
    # Production: WhiteNoise hashes filenames + serves compressed files
    STORAGES = {
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
    }
else:
    # Development: serve directly from STATICFILES_DIRS, no manifest needed
    STORAGES = {
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
    }

# ── CORS ──────────────────────────────────────────────────────────────────────
if IS_PRODUCTION:
    CORS_ALLOWED_ORIGINS = [
        'https://simphantom.com',
        'https://www.simphantom.com',
    ]
else:
    CORS_ALLOW_ALL_ORIGINS = True

# ── Security headers (all environments) ──────────────────────────────────────
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY      = 'strict-origin-when-cross-origin'
X_FRAME_OPTIONS             = 'DENY'

# ── Security (production only) ────────────────────────────────────────────────
if IS_PRODUCTION:
    SESSION_COOKIE_SECURE          = True
    CSRF_COOKIE_SECURE             = True
    # Set to False when SSL is terminated by Nginx / a load balancer above Django
    SECURE_SSL_REDIRECT            = config('SECURE_SSL_REDIRECT', default=False, cast=bool)
    SECURE_HSTS_SECONDS            = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD            = True
    # Trust X-Forwarded-Proto header set by Nginx
    SECURE_PROXY_SSL_HEADER        = ('HTTP_X_FORWARDED_PROTO', 'https')

# ── REST Framework ────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
}

# ── Cache (used for rate limiting) ────────────────────────────────────────────
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

# ── API keys ──────────────────────────────────────────────────────────────────
FIVESIM_API_KEY    = config('FIVESIM_API_KEY')
PAYSTACK_SECRET    = config('PAYSTACK_SECRET')
PAYSTACK_PUBLIC_KEY = config('PAYSTACK_PUBLIC_KEY', default='')

BRIGHTDATA_API_KEY     = config('BRIGHTDATA_API_KEY', default='')
BRIGHTDATA_ZONE_NAME   = config('BRIGHTDATA_ZONE_NAME', default='SimPhantom_res')
BRIGHTDATA_CUSTOMER_ID = config('BRIGHTDATA_CUSTOMER_ID', default='')
BRIGHTDATA_ZONE_PASS   = config('BRIGHTDATA_ZONE_PASS', default='')

TWILIO_ACCOUNT_SID  = config('TWILIO_ACCOUNT_SID', default='')
TWILIO_AUTH_TOKEN   = config('TWILIO_AUTH_TOKEN', default='')
TWILIO_FROM_NUMBER  = config('TWILIO_FROM_NUMBER', default='')

ESIMCARD_API_TOKEN  = config('ESIMCARD_API_TOKEN', default='')

CLOUDFLARE_TURNSTILE_SECRET_KEY = config('CLOUDFLARE_TURNSTILE_SECRET_KEY', default='')

# ── Session timeout ───────────────────────────────────────────────────────────
SESSION_COOKIE_AGE      = 1800   # 30 min max lifetime (server enforced)
SESSION_SAVE_EVERY_REQUEST = True  # reset expiry on every request

AUTH_USER_MODEL = 'accounts.User'

# ── Google OAuth (django-allauth) ─────────────────────────────────────────────
SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

ACCOUNT_LOGIN_METHODS        = {'email'}
ACCOUNT_SIGNUP_FIELDS        = ['email*', 'password1*', 'password2*']
ACCOUNT_EMAIL_VERIFICATION   = 'none'
LOGIN_REDIRECT_URL           = '/dashboard/'
ACCOUNT_LOGOUT_REDIRECT_URL  = '/'
SOCIALACCOUNT_AUTO_SIGNUP    = True
SOCIALACCOUNT_LOGIN_ON_GET   = True
SOCIALACCOUNT_ADAPTER        = 'accounts.adapters.SocialAccountAdapter'

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': config('GOOGLE_CLIENT_ID', default=''),
            'secret':    config('GOOGLE_CLIENT_SECRET', default=''),
        },
        'SCOPE':           ['profile', 'email'],
        'AUTH_PARAMS':     {'access_type': 'online'},
        'OAUTH_PKCE_ENABLED': True,
    }
}

# ── Email (Brevo SMTP relay) ──────────────────────────────────────────────────
if DJANGO_ENV == 'development':
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    EMAIL_BACKEND       = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST          = 'smtp-relay.brevo.com'
    EMAIL_PORT          = 587
    EMAIL_USE_TLS       = True
    EMAIL_HOST_USER     = config('EMAIL_HOST_USER', default='')
    EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL  = f'{config("EMAIL_FROM_NAME", default="SimPhantom")} <{config("EMAIL_FROM", default="noreply@simphantom.com")}>'
ADMIN_NOTIFY_EMAIL  = config('ADMIN_NOTIFY_EMAIL', default='simphantom1@gmail.com')

# ── Logging ───────────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'server.log',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'main': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'payments': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'orders': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'accounts': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'support': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
