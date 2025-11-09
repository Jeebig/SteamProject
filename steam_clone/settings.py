import os
from pathlib import Path
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    def load_dotenv(*args, **kwargs):
        return False

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
_env_path = BASE_DIR / '.env'
if _env_path.exists():
    load_dotenv(_env_path)

def _get_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}

SECRET_KEY = os.getenv('SECRET_KEY', 'replace-me-in-production')
DEBUG = _get_bool('DEBUG', True)

_hosts = [h.strip() for h in os.getenv('ALLOWED_HOSTS', '').split(',') if h.strip()]
ALLOWED_HOSTS = _hosts if _hosts else []

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
    'social_django',
    'store',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # Activate user preferred_language for UI
    'store.middleware.LanguagePreferenceMiddleware',
    # Обновление last_seen для отображения статуса онлайн
    'store.middleware.ActivityMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'steam_clone.urls'

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
                # expose MEDIA_URL and related media context
                'django.template.context_processors.media',
                # social auth
                'social_django.context_processors.backends',
                'social_django.context_processors.login_redirect',
            ],
        },
    },
]

WSGI_APPLICATION = 'steam_clone.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

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

LANGUAGE_CODE = 'en'

LANGUAGES = [
    ('en', 'English'),
    ('uk', 'Українська'),
    ('ru', 'Русский'),
]

TIME_ZONE = 'UTC'

USE_I18N = True
USE_L10N = True
USE_TZ = True

LOCALE_PATHS = [BASE_DIR / 'locale']

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
# Where collectstatic will place files for production/static hosting
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Recommended when deploying behind a known domain (e.g., PythonAnywhere)
_csrf_origins = [o.strip() for o in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()]
if _csrf_origins:
    CSRF_TRUSTED_ORIGINS = _csrf_origins

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Auth redirects: avoid /accounts/profile/ 404 on successful login
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# Social auth: Steam OpenID
AUTHENTICATION_BACKENDS = (
    'social_core.backends.steam.SteamOpenId',
    'django.contrib.auth.backends.ModelBackend',
)

SOCIAL_AUTH_STEAM_API_KEY = os.getenv('STEAM_API_KEY', '')
SOCIAL_AUTH_LOGIN_REDIRECT_URL = '/'
SOCIAL_AUTH_LOGIN_ERROR_URL = '/accounts/login/'
SOCIAL_AUTH_PIPELINE = (
    'social_core.pipeline.social_auth.social_details',
    'social_core.pipeline.social_auth.social_uid',
    'social_core.pipeline.social_auth.auth_allowed',
    'social_core.pipeline.social_auth.social_user',
    'social_core.pipeline.user.get_username',
    'social_core.pipeline.user.create_user',
    'social_core.pipeline.social_auth.associate_user',
    'social_core.pipeline.social_auth.load_extra_data',
    'social_core.pipeline.user.user_details',
    # Custom: sync Steam profile and library
    'store.auth_pipeline.sync_steam',
)

# Performance feature flags
# Disable remote Steam tags fetching during server-side render by default
STORE_FETCH_STEAM_TAGS = False

# Currency rates fetching
# Avoid blocking requests to external API on page render. Use DB cache/fallback instead.
# Set to True to enable live fetch in the background or when needed.
CURRENCY_FETCH_ENABLED = False
# Short network timeout when live fetch is enabled
CURRENCY_FETCH_TIMEOUT = 1.2

# Price drop alerts: default percent threshold
PRICE_DROP_THRESHOLD_PERCENT = 15

# Email settings (заполните реальные значения в продакшене)
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')  # prod: django.core.mail.backends.smtp.EmailBackend
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'support@steamclone.local')
SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL', 'support@steamclone.local')
# Имя учётной записи администратора поддержки (должно существовать в БД)
SUPPORT_ADMIN_USERNAME = os.getenv('SUPPORT_ADMIN_USERNAME', 'admin')
