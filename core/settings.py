import os
from pathlib import Path
from datetime import timedelta
import dj_database_url
from dotenv import load_dotenv  # Çevresel değişkenleri okumak için ekledik
from django.core.exceptions import ImproperlyConfigured

# .env dosyasını zorla oku (Böylece şifreyi kodun içine yazmamıza gerek kalmaz)
load_dotenv()

# Proje dizin yolları
BASE_DIR = Path(__file__).resolve().parent.parent

def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in {'1', 'true', 'yes', 'on'}


def env_list(name, default=''):
    return [value.strip() for value in os.environ.get(name, default).split(',') if value.strip()]


# --- GÜVENLİK AYARLARI ---
DEBUG = env_bool('DEBUG', False)
SECRET_KEY = os.environ.get('SECRET_KEY')

if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-local-development-only'
    else:
        raise ImproperlyConfigured('Production ortamında SECRET_KEY tanımlanmalıdır.')

ALLOWED_HOSTS = env_list(
    'ALLOWED_HOSTS',
    'localhost,127.0.0.1' if DEBUG else 'e-teacher.onrender.com',
)

# Render HTTPS sonlandırmasını Django'ya doğru aktarır.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', not DEBUG)
SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '0' if DEBUG else '31536000'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', not DEBUG)
SECURE_HSTS_PRELOAD = env_bool('SECURE_HSTS_PRELOAD', not DEBUG)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

# --- UYGULAMALAR ---
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Bizim Eklediklerimiz
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'api',
    'whitenoise.runserver_nostatic', # Statik dosyalar için eklendi
]


# --- MIDDLEWARE (Sıralama Önemlidir) ---
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
]

ROOT_URLCONF = 'core.urls'

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

WSGI_APPLICATION = 'core.wsgi.application'

# --- VERİTABANI ---
# ARTIK ŞİFRE KODDA DEĞİL! Direkt olarak .env dosyasından veya Render ortamından çekecek.
DATABASES = {
    'default': dj_database_url.config(
        default=os.environ.get('DATABASE_URL'), 
        conn_max_age=600
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]

# --- DİL VE SAAT (Türkiye'ye Özel) ---
LANGUAGE_CODE = 'tr-tr'
TIME_ZONE = 'Europe/Istanbul'
USE_I18N = True
USE_TZ = True

# --- STATİK DOSYA AYARLARI (RENDER HATASINI ÇÖZEN KISIM) ---
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
# Statik dosyaların sıkıştırılması için (Whitenoise)
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- BİZİM REACT VE JWT AYARLARIMIZ ---
CORS_ALLOW_ALL_ORIGINS = False  # Herkese açık kapıyı kapatıyoruz
CORS_ALLOW_CREDENTIALS = True   # Token ve Cookie geçişine izin veriyoruz

# Sadece bizim projelerimizin Backend'e bağlanmasına izin ver
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",  # Klasik React Web
    "http://localhost:5173",  # Vite React Web
    "http://localhost:8081",  # Expo Mobil (Web Modu)
    "http://127.0.0.1:8081",  # Expo Mobil (Web Modu Alternatif IP)
    "https://e-teacher-mobile.vercel.app", 
    "https://e-teacher-web.vercel.app", # VERCEL WEB FRONTEND ADRESİ EKLENDİ
]

# CSRF (Güvenlik) hatalarını önlemek için Vercel adresini güvenilir ilan ediyoruz
CSRF_TRUSTED_ORIGINS = [
    "https://e-teacher-mobile.vercel.app",
    "https://e-teacher-web.vercel.app",
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
}

# --- GOOGLE OAUTH VE SESSION GÜVENLİK AYARLARI ---
SESSION_COOKIE_SAMESITE = 'Lax' if DEBUG else 'None'
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = 'Lax' if DEBUG else 'None'
CSRF_COOKIE_SECURE = not DEBUG
