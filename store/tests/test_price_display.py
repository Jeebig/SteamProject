from decimal import Decimal
from django.test import SimpleTestCase
from django.utils import translation
from store.templatetags.store_extras import price_display


class PriceDisplayI18NTests(SimpleTestCase):
    def test_free_label_translations(self):
        for lang, expected in [
            ('ru', 'Бесплатно'),
            ('uk', 'Безкоштовно'),
            ('en', 'Free'),  # assumes English catalog has translation
        ]:
            with translation.override(lang):
                html = price_display(Decimal('0.00'), 'USD', preferred_currency='USD')
                self.assertIn(expected, html, f"Missing free label for {lang}")

    def test_discount_block_structure(self):
        # discount: original 59.99 -> price 29.99, 50%
        with translation.override('ru'):
            html = price_display(Decimal('29.99'), 'USD', preferred_currency='USD', original_price=Decimal('59.99'), discount_percent=50)
            self.assertIn('-50%', html)
            self.assertIn('59.99 USD', html)
            self.assertIn('29.99 USD', html)

    def test_conversion_approximation(self):
        # Force conversion by differing preferred currency
        with translation.override('uk'):
            html = price_display(Decimal('10.00'), 'USD', preferred_currency='UAH')
            # Should contain approximation marker (≈)
            self.assertIn('≈', html)
            self.assertIn('UAH', html)
