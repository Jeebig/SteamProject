from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from store.models import Game, Developer, Genre, Review
from decimal import Decimal
import json

DUMMY_GIF = (b'GIF89a\x01\x00\x01\x00\x80\x00\x00' \
             b'\x00\x00\x00\xFF\xFF\xFF!\xF9\x04\x01\x00\x00\x00\x00,' \
             b'\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;')

class SearchRankingTests(TestCase):
    def setUp(self):
        # Create developer & genre
        self.dev = Developer.objects.create(name='StarForge Studios')
        self.genre = Genre.objects.create(name='Space Exploration')
        # Helper to create game with cover
        def make(title, discount=0):
            img = SimpleUploadedFile('cover.gif', DUMMY_GIF, content_type='image/gif')
            g = Game.objects.create(title=title, price=Decimal('10.00'), currency='USD', appid=1000 + Game.objects.count(), developer=self.dev, discount_percent=discount, cover_image=img)
            g.genres.add(self.genre)
            return g
        self.g_exact = make('Star')
        self.g_prefix1 = make('Starfall', discount=15)
        self.g_prefix2 = make('Stardust')
        self.g_contains1 = make('XStarX')
        self.g_contains2 = make('A Star Tale')
        # Add one review to one prefix game to ensure rating fields don't override rank order except after exact
        user = get_user_model().objects.create_user(username='rater', password='pw')
        Review.objects.create(user=user, game=self.g_prefix1, rating=8, text='Nice')

    def test_search_suggest_ordering(self):
        url = reverse('store:search_suggest') + '?q=star'
        resp = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content.decode('utf-8'))
        items = data.get('items', [])
        titles = [i['title'] for i in items]
        # Ensure exact match first
        self.assertTrue(titles, 'No suggestions returned')
        self.assertEqual(titles[0], 'Star')
        # Prefix matches should appear before contains matches
        # Find indices
        idx_prefix1 = titles.index('Starfall') if 'Starfall' in titles else -1
        idx_prefix2 = titles.index('Stardust') if 'Stardust' in titles else -1
        idx_contains1 = titles.index('XStarX') if 'XStarX' in titles else 999
        idx_contains2 = titles.index('A Star Tale') if 'A Star Tale' in titles else 999
        self.assertTrue(idx_prefix1 > 0 and idx_prefix2 > 0, 'Prefix games missing in suggestions')
        self.assertTrue(idx_prefix1 < idx_contains1 and idx_prefix2 < idx_contains1, 'Prefix ranking broken (contains came earlier)')
        self.assertTrue(idx_contains1 < idx_contains2 or idx_contains2 == 999, 'Position-based scoring for contains not preserved')

    def test_catalog_search_rank(self):
        url = reverse('store:game_list') + '?q=star'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # Extract context games from response by their slugs in order of appearance
        # Simple heuristic: find occurrences of href links to /game/<slug>/ in raw HTML order
        html = resp.content.decode('utf-8')
        import re
        slugs = re.findall(r'/game/([a-z0-9\-]+)/', html)
        # Map back to titles for known games
        slug_to_title = {self.g_exact.slug: 'Star', self.g_prefix1.slug: 'Starfall', self.g_prefix2.slug: 'Stardust', self.g_contains1.slug: 'XStarX', self.g_contains2.slug: 'A Star Tale'}
        ordered_titles = [slug_to_title.get(s) for s in slugs if s in slug_to_title]
        # Expect exact first
        if ordered_titles:
            self.assertEqual(ordered_titles[0], 'Star')
        # Prefix titles should appear before contains ones when present
        # Derive indices ignoring missing entries
        def safe_index(lst, val):
            return lst.index(val) if val in lst else 999
        idx_pf1 = safe_index(ordered_titles, 'Starfall')
        idx_pf2 = safe_index(ordered_titles, 'Stardust')
        idx_ct1 = safe_index(ordered_titles, 'XStarX')
        idx_ct2 = safe_index(ordered_titles, 'A Star Tale')
        self.assertTrue(idx_pf1 < idx_ct1 or idx_ct1 == 999)
        self.assertTrue(idx_pf2 < idx_ct1 or idx_ct1 == 999)
