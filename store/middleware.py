from django.utils import timezone, translation
from datetime import timedelta
from django.conf import settings

class LanguagePreferenceMiddleware:
    """Activate per-user preferred_language stored in UserProfile.

    Runs after AuthenticationMiddleware. Falls back to LANGUAGE_CODE.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        lang = None
        if user and user.is_authenticated:
            prof = getattr(user, 'profile', None)
            if prof:
                cand = getattr(prof, 'preferred_language', None)
                # validate against settings.LANGUAGES
                if cand and any(cand == code for code, _ in getattr(settings, 'LANGUAGES', [])):
                    lang = cand
        if not lang:
            lang = getattr(settings, 'LANGUAGE_CODE', 'en')
        try:
            translation.activate(lang)
            request.LANGUAGE_CODE = lang
        except Exception:
            pass
        return self.get_response(request)

class ActivityMiddleware:
    """Обновляет profile.last_seen для авторизованных пользователей.

    Чтобы снизить нагрузку, обновляем не чаще одного раза в N секунд.
    """
    THROTTLE_SECONDS = 60

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            prof = getattr(user, 'profile', None)
            if prof:
                now = timezone.now()
                ls = getattr(prof, 'last_seen', None)
                should_update = False
                if ls is None:
                    should_update = True
                else:
                    delta = (now - ls)
                    if delta.total_seconds() >= self.THROTTLE_SECONDS:
                        should_update = True
                if should_update:
                    prof.last_seen = now
                    try:
                        prof.save(update_fields=['last_seen'])
                    except Exception:
                        # В случае ошибки сохранения — игнорируем (не критично)
                        pass
        return self.get_response(request)
