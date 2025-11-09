from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from .models import Game


class GameSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.8

    def items(self):
        # Only index games that have valid slugs and appids
        return Game.objects.filter(appid__isnull=False).only('slug', 'updated_at')

    def location(self, obj):
        return reverse('store:game_detail', args=[obj.slug])

    def lastmod(self, obj):
        return getattr(obj, 'updated_at', None)


class StaticViewSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.5

    def items(self):
        return [
            'store:home',
            'store:game_list',
            'store:discounts',
            'store:charts',
            'store:recommendations',
            'store:support',
        ]

    def location(self, item):
        return reverse(item)
