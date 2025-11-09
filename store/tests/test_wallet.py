from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.conf import settings
from store.models import UserProfile, WalletTransaction, Game, Order, OrderItem


class WalletTests(TestCase):
    def setUp(self):
        settings.CURRENCY_FETCH_ENABLED = False  # avoid network in tests
        User = get_user_model()
        self.user = User.objects.create_user(username='wal', password='pw')
        self.profile = UserProfile.objects.create(user=self.user, preferred_currency='USD')

    def test_topup_rejects_below_minimum(self):
        self.client.login(username='wal', password='pw')
        url = reverse('store:wallet_topup')
        resp = self.client.post(url, data={'amount': '0.50', 'currency': 'USD'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.balance, Decimal('0.00'))
        self.assertEqual(WalletTransaction.objects.filter(user=self.user).count(), 0)

    def test_topup_same_currency_creates_transaction(self):
        self.client.login(username='wal', password='pw')
        url = reverse('store:wallet_topup')
        resp = self.client.post(url, data={'amount': '2.00', 'currency': 'USD'})
        self.assertEqual(resp.status_code, 302)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.balance, Decimal('2.00'))
        tx = WalletTransaction.objects.filter(user=self.user, kind='topup').first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.amount, Decimal('2.00'))
        self.assertEqual(tx.currency, 'USD')

    def test_topup_foreign_currency_converts_and_logs_source(self):
        self.client.login(username='wal', password='pw')
        url = reverse('store:wallet_topup')
        # Using fallback conversion rates: 41 UAH ≈ 1 USD
        resp = self.client.post(url, data={'amount': '41.00', 'currency': 'UAH'})
        self.assertEqual(resp.status_code, 302)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.balance, Decimal('1.00'))
        tx = WalletTransaction.objects.filter(user=self.user, kind='topup').order_by('-created_at').first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.source_currency, 'UAH')
        self.assertEqual(tx.source_amount, Decimal('41.00'))

    def test_payment_deducts_balance_and_logs_transaction(self):
        self.profile.add_balance(Decimal('10.00'), 'USD')
        g = Game.objects.create(title='X', slug='x', price=Decimal('5.00'), currency='USD')
        self.client.login(username='wal', password='pw')
        # create pending order manually (faster than full cart flow)
        order = Order.objects.create(user=self.user, total_price=Decimal('5.00'), currency='USD', status='pending')
        OrderItem.objects.create(order=order, game=g, quantity=1, price=Decimal('5.00'), currency='USD')
        pay_url = reverse('store:pay', kwargs={'pk': order.id})
        resp = self.client.post(pay_url, data={'use_wallet': '1'})
        self.assertEqual(resp.status_code, 302)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.balance, Decimal('5.00'))
        tx = WalletTransaction.objects.filter(user=self.user, kind='purchase_deduct').first()
        self.assertIsNotNone(tx)
        self.assertTrue(tx.amount < 0)
        self.assertEqual(tx.currency, 'USD')
