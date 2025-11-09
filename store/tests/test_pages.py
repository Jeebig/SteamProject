from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model


class PagesSmokeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='u1', password='p1')

    def test_homepage_loads(self):
        url = reverse('store:home')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'<div', resp.content)

    def test_friends_requires_login(self):
        url = reverse('store:friends')
        resp = self.client.get(url)
        # expect redirect to login
        self.assertIn(resp.status_code, (302, 301))

    def test_friends_page_loads_when_logged_in(self):
        self.client.login(username='u1', password='p1')
        url = reverse('store:friends')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'\xd0\x94\xd1\x80\xd1\x83\xd0\xb7\xd1\x8c\xd1\x8f', resp.content)  # 'Друзья' in bytes
