from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth import get_user_model
from decimal import Decimal
from store.models import Game, UserProfile, Notification, PriceSnapshot

class PriceDropAlertTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='wish', password='pw', email='wish@example.com')
        self.profile = UserProfile.objects.create(user=self.user, preferred_currency='USD')
        self.game = Game.objects.create(title='GalaxyRun', slug='galaxy-run', price=Decimal('20.00'), currency='USD', appid=777)
        self.profile.wishlist.add(self.game)

    def test_snapshot_and_no_drop_no_notification(self):
        call_command('snapshot_prices', threshold=10)
        self.assertEqual(PriceSnapshot.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(kind='price_drop').count(), 0)

    def test_price_drop_generates_notification(self):
        # Day 1 snapshot
        call_command('snapshot_prices', threshold=10)
        # Simulate price drop
        self.game.price = Decimal('14.00')
        self.game.save(update_fields=['price'])
        # Day 2 snapshot triggers alert (30% drop)
        call_command('snapshot_prices', threshold=10)
        self.assertEqual(Notification.objects.filter(kind='price_drop').count(), 1)
        n = Notification.objects.filter(kind='price_drop').first()
        self.assertIn('GalaxyRun', n.payload.get('game_title',''))
        self.assertTrue(int(n.payload.get('percent', 0)) >= 10)

    def test_free_now_counts_as_drop(self):
        # First snapshot
        call_command('snapshot_prices', threshold=5)
        # Drop to free
        self.game.price = Decimal('0.00')
        self.game.save(update_fields=['price'])
        call_command('snapshot_prices', threshold=5)
        self.assertEqual(Notification.objects.filter(kind='price_drop').count(), 1)
