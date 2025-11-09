from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from store.models import UserProfile

User = get_user_model()

class UsernameRateLimitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='rateuser', password='pass123')
        UserProfile.objects.get_or_create(user=self.user)
        self.client.login(username='rateuser', password='pass123')

    def _post(self, new_username):
        url = reverse('store:profile_edit')
        data = {
            'steam_persona': '',
            'bg_appid': '',
            'bio': '',
            'theme_color': '',
            'new_username': new_username,
        }
        return self.client.post(url, data=data)

    def test_two_changes_second_blocked(self):
        # first change OK
        r1 = self._post('firstchange')
        self.assertEqual(r1.status_code, 302)
        # second immediate attempt should be blocked
        r2 = self._post('secondchange')
        self.assertEqual(r2.status_code, 200)
        self.assertContains(r2, 'не чаще одного раза в сутки')
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'firstchange')

    def test_change_after_24h_allowed(self):
        r1 = self._post('nickone')
        self.assertEqual(r1.status_code, 302)
        # simulate passage of >24h
        prof = self.user.profile
        prof.last_username_change = timezone.now() - timedelta(hours=25)
        prof.save(update_fields=['last_username_change'])
        r2 = self._post('nicktwo')
        self.assertEqual(r2.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'nicktwo')
