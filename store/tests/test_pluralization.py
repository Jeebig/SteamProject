from django.test import SimpleTestCase
from django.template import Context, Template
from django.utils.translation import activate

class PluralizationTagTests(SimpleTestCase):
    def render(self, tpl: str, **ctx):
        t = Template('{% load store_extras %}' + tpl)
        return t.render(Context(ctx)).strip()

    def setUp(self):
        # Use English to test base msgids; adjust if default language differs.
        activate('en')

    def test_reviews_pluralization(self):
        self.assertEqual(self.render('{% n_reviews 1 %}'), '1 review')
        self.assertEqual(self.render('{% n_reviews 2 %}'), '2 reviews')

    def test_games_pluralization(self):
        self.assertEqual(self.render('{% n_games 1 %}'), '1 game')
        self.assertEqual(self.render('{% n_games 3 %}'), '3 games')

    def test_minutes_pluralization(self):
        self.assertEqual(self.render('{% n_minutes 1 %}'), '1 minute')
        self.assertEqual(self.render('{% n_minutes 5 %}'), '5 minutes')

    def test_zero_edge_case(self):
        # Zero should use plural form in English
        self.assertEqual(self.render('{% n_reviews 0 %}'), '0 reviews')
        self.assertEqual(self.render('{% n_games 0 %}'), '0 games')
        self.assertEqual(self.render('{% n_minutes 0 %}'), '0 minutes')
