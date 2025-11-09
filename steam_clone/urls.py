from django.contrib import admin
from django.urls import path, include
from django.contrib.sitemaps import views as sitemap_views
from store.sitemaps import GameSitemap, StaticViewSitemap
from django.views.generic import TemplateView
from store.views import SafeLoginView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('store.urls')),
    path('oauth/', include('social_django.urls', namespace='social')),
    # Override login to allow email or username and sanitize next param
    path('accounts/login/', SafeLoginView.as_view(), name='login'),
    # include Django auth views for login/logout/password management
    path('accounts/', include('django.contrib.auth.urls')),
    # SEO: sitemap.xml and robots.txt
    path('sitemap.xml', sitemap_views.sitemap, { 'sitemaps': {
        'static': StaticViewSitemap,
        'games': GameSitemap,
    } }, name='sitemap'),
    path('robots.txt', TemplateView.as_view(template_name='robots.txt', content_type='text/plain')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
