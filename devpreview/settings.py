"""Development only: reusable frontend with no database or live RAG service."""

SECRET_KEY = "local-frontend-preview-only-not-for-deployment"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
INSTALLED_APPS = ["django.contrib.staticfiles", "frontend"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "devpreview.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
}]
STATIC_URL = "static/"
USE_TZ = True
