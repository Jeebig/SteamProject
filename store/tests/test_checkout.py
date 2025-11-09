from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from store.models import Game, CartItem, Order, OrderItem


class CheckoutFlowTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="buyer", password="pass1234")
        # Two games with different currencies to test conversion path
        self.g1 = Game.objects.create(title="Game USD", slug="game-usd", price=Decimal("10.00"), currency="USD")
        self.g2 = Game.objects.create(title="Game EUR", slug="game-eur", price=Decimal("5.00"), currency="EUR")

    def login(self):
        self.client.login(username="buyer", password="pass1234")

    def test_checkout_then_fake_pay_clears_cart_and_creates_order(self):
        self.login()
        # Add items to cart
        CartItem.objects.create(user=self.user, game=self.g1, quantity=2)
        CartItem.objects.create(user=self.user, game=self.g2, quantity=1)

        # Step 1: POST checkout -> creates pending order and redirects to pay
        resp = self.client.post(reverse("store:checkout"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/pay/", resp.headers.get("Location", ""))

        # Fetch created order
        order = Order.objects.filter(user=self.user).order_by("-id").first()
        self.assertIsNotNone(order)
        self.assertEqual(order.status, "pending")
        self.assertGreater(order.total_price, Decimal("0.00"))
        # Snapshot must exist and reflect 2 entries
        self.assertEqual(OrderItem.objects.filter(order=order).count(), 2)

        # Step 2: POST to payment -> marks paid, clears cart
        pay_url = reverse("store:pay", args=[order.id])
        resp2 = self.client.post(pay_url)
        self.assertEqual(resp2.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, "paid")
        # Cart emptied
        self.assertEqual(CartItem.objects.filter(user=self.user).count(), 0)

    def test_checkout_empty_cart_redirects(self):
        self.login()
        resp = self.client.post(reverse("store:checkout"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("store:cart"), resp.headers.get("Location", ""))
