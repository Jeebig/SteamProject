from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from store.models import Game, CartItem


class CartAddTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="u1", password="p1")
        self.game = Game.objects.create(title="G", slug="g", price=Decimal("3.00"), currency="USD")

    def test_add_to_cart_from_detail(self):
        self.client.login(username="u1", password="p1")
        url = reverse("store:cart_add", args=[self.game.slug])
        resp = self.client.post(url, data={"next": reverse("store:cart")})
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("store:cart"), resp.headers.get("Location", ""))
        self.assertTrue(CartItem.objects.filter(user=self.user, game=self.game).exists())
