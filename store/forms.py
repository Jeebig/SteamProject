from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import authenticate, get_user_model
from django.db.models import Q
from decimal import Decimal
from .models import UserProfile, SupportTicket, Review
from django.utils import timezone


class ProfileSettingsForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = (
            'preferred_language', 'preferred_currency', 'privacy',
            'notify_profile_comment', 'notify_friend_request', 'notify_friend_accept',
            'email_profile_comment', 'email_friend_events',
            'notify_price_drop', 'email_price_drop',
            'comment_privacy', 'friend_request_privacy',
        )
        widgets = {
            'preferred_language': forms.Select(attrs={'class': 'input'}),
            'preferred_currency': forms.Select(attrs={'class': 'input'}),
            'privacy': forms.Select(attrs={'class': 'input'}),
            'comment_privacy': forms.Select(attrs={'class': 'input'}),
            'friend_request_privacy': forms.Select(attrs={'class': 'input'}),
        }


class GeneralSettingsForm(forms.ModelForm):
    """Базовые общие настройки аккаунта (язык + валюта).

    Выделены из ProfileSettingsForm для более модульного интерфейса SettingsView.
    """
    class Meta:
        model = UserProfile
        fields = ('preferred_language', 'preferred_currency')
        widgets = {
            'preferred_language': forms.Select(attrs={'class': 'input'}),
            'preferred_currency': forms.Select(attrs={'class': 'input'}),
        }


class PrivacySettingsForm(forms.ModelForm):
    """Настройки приватности профиля и взаимодействия."""
    class Meta:
        model = UserProfile
        fields = ('privacy', 'comment_privacy', 'friend_request_privacy')
        widgets = {
            'privacy': forms.Select(attrs={'class': 'input'}),
            'comment_privacy': forms.Select(attrs={'class': 'input'}),
            'friend_request_privacy': forms.Select(attrs={'class': 'input'}),
        }


class NotificationSettingsForm(forms.ModelForm):
    """Настройки уведомлений (внутренних и email)."""
    class Meta:
        model = UserProfile
        fields = (
            'notify_profile_comment', 'notify_friend_request', 'notify_friend_accept',
            'email_profile_comment', 'email_friend_events',
            'notify_price_drop', 'email_price_drop'
        )
        widgets = {f: forms.CheckboxInput(attrs={'class': 'mr-2'}) for f in fields}


class ProfileAppearanceForm(forms.ModelForm):
    remove_avatar = forms.BooleanField(required=False, widget=forms.CheckboxInput(attrs={'class': 'mr-2'}))
    # Позволяет менять логин (username) если аккаунт не привязан к Steam
    new_username = forms.CharField(required=False, max_length=150, widget=forms.TextInput(attrs={'class': 'input', 'placeholder': 'Никнейм (логин)'}))
    class Meta:
        model = UserProfile
        fields = (
            'steam_persona', 'avatar', 'bg_appid', 'profile_bg', 'bio', 'theme_color'
        )
        widgets = {
            'steam_persona': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Отображаемое имя'}),
            'avatar': forms.ClearableFileInput(attrs={'class': 'input'}),
            'bg_appid': forms.NumberInput(attrs={'class': 'input', 'placeholder': 'AppID для фонового баннера'}),
            'profile_bg': forms.ClearableFileInput(attrs={'class': 'input'}),
            # лимитируем био на уровне формы для UX (модель не ограничивает)
            'bio': forms.Textarea(attrs={'class': 'input', 'rows': 4, 'placeholder': 'Краткое описание профиля', 'maxlength': '300'}),
            'theme_color': forms.TextInput(attrs={'class': 'input', 'placeholder': '#1b6b80 или ключ'}),
        }

    def __init__(self, *args, **kwargs):
        self._user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        # Инициализируем никнейм текущим username, если разрешено менять (нет steam_id)
        try:
            if self._user and hasattr(self._user, 'profile') and not self._user.profile.steam_id:
                self.fields['new_username'].initial = self._user.username
            else:
                # если смена ника не разрешена — спрячем поле в шаблоне (можем оставить, но пусть будет явно)
                pass
        except Exception:
            pass

    def clean_new_username(self):
        val = (self.cleaned_data.get('new_username') or '').strip()
        if not val:
            return ''
        # Разрешаем менять ник только если нет Steam-привязки
        # Предпочитаем проверять по self._user.profile (самый актуальный объект)
        if self._user and hasattr(self._user, 'profile'):
            if getattr(self._user.profile, 'steam_id', ''):
                raise forms.ValidationError('Никнейм меняется в аккаунте Steam, так как профиль привязан к Steam.')
        # Дополнительная защита: если в instance уже есть steam_id
        prof = getattr(self, 'instance', None)
        if prof and getattr(prof, 'steam_id', ''):
            raise forms.ValidationError('Никнейм меняется в аккаунте Steam, так как профиль привязан к Steam.')
        # Проверим уникальность (без учёта регистра)
        User = get_user_model()
        qs = User._default_manager.filter(Q(username__iexact=val))
        if self._user and getattr(self._user, 'pk', None):
            qs = qs.exclude(pk=self._user.pk)
        if qs.exists():
            raise forms.ValidationError('Такой ник уже занят.')
        # Rate-limit: не чаще 1 раза в сутки
        prof = getattr(self._user, 'profile', None)
        if prof and self._user.username.lower() != val.lower():
            last = getattr(prof, 'last_username_change', None)
            if last:
                try:
                    now = timezone.now()
                    # Приведём naive timestamp к aware, если нужно, чтобы разница не упала с исключением
                    if timezone.is_naive(last) and not timezone.is_naive(now):
                        from django.utils.timezone import make_aware, get_current_timezone
                        last = make_aware(last, get_current_timezone())
                    delta_sec = (now - last).total_seconds()
                except Exception:
                    # Если что-то пошло не так при вычислении — считаем что ограничение действует (fail-safe)
                    delta_sec = 0
                if delta_sec < 24 * 3600:
                    raise forms.ValidationError('Вы можете менять ник не чаще одного раза в сутки.')
        return val

    def clean_theme_color(self):
        """Валидация HEX цвета акцента (#RRGGBB). Пустое значение допускается (означает дефолт)."""
        val = (self.cleaned_data.get('theme_color') or '').strip()
        if not val:
            return ''
        import re
        if not re.fullmatch(r'#([0-9A-Fa-f]{6})', val):
            raise forms.ValidationError('Используйте HEX формат #RRGGBB (например, #1b6b80).')
        # Нормализуем в нижний регистр для единообразия хранения
        return val.lower()

    def clean_bio(self):
        """Server-side limit and basic normalization for bio.

        - Trim whitespace
        - Truncate to 2000 chars (UI may set a smaller maxlength, but enforce safely)
        """
        bio = self.cleaned_data.get('bio') or ''
        try:
            bio = str(bio).strip()
        except Exception:
            bio = ''
        # hard limit
        if len(bio) > 2000:
            bio = bio[:2000]
        return bio

    def save(self, commit=True):
        inst = super().save(commit=False)
        if self.cleaned_data.get('remove_avatar'):
            try:
                if inst.avatar:
                    inst.avatar.delete(save=False)
                inst.avatar = None
            except Exception:
                pass
        # Применяем смену никнейма, если разрешено и задано
        try:
            new_username = (self.cleaned_data.get('new_username') or '').strip()
            if new_username and self._user and hasattr(self._user, 'profile') and not self._user.profile.steam_id:
                if self._user.username != new_username:
                    self._user.username = new_username
                    self._user.save(update_fields=['username'])
                    # обновим отметку времени смены ника на инстансе формы (во избежание перезаписи)
                    try:
                        inst.last_username_change = timezone.now()
                    except Exception:
                        pass
        except Exception:
            pass
        if commit:
            inst.save()
        return inst


class SupportTicketForm(forms.ModelForm):
    # Email берём из аккаунта, поэтому поле не показываем
    class Meta:
        model = SupportTicket
        fields = ('category', 'category_other', 'subject', 'message')
        widgets = {
            'category': forms.Select(attrs={'class': 'w-full px-3 py-2 rounded bg-gray-800 text-gray-100'}),
            'category_other': forms.TextInput(attrs={'class': 'w-full px-3 py-2 rounded bg-gray-800 text-gray-100', 'placeholder': 'Уточните тему'}) ,
            'subject': forms.TextInput(attrs={'class': 'w-full px-3 py-2 rounded bg-gray-800 text-gray-100', 'placeholder': 'Тема обращения'}),
            'message': forms.Textarea(attrs={'class': 'w-full px-3 py-2 rounded bg-gray-800 text-gray-100', 'rows': 6, 'placeholder': 'Опишите проблему максимально подробно'}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('category') == 'other' and not (cleaned.get('category_other') or cleaned.get('subject')):
            self.add_error('category_other', 'Пожалуйста, уточните тему для категории "Другое"')
        return cleaned


class ReviewForm(forms.ModelForm):
    rating = forms.DecimalField(min_value=Decimal('1.0'), max_value=Decimal('5.0'), decimal_places=1, widget=forms.NumberInput(attrs={
        'class': 'w-20 px-2 py-1 rounded bg-gray-800 text-gray-100', 'step': '0.5'
    }))
    text = forms.CharField(required=True, min_length=10, widget=forms.Textarea(attrs={
        'class': 'w-full px-3 py-2 rounded bg-gray-800 text-gray-100', 'rows': 4,
        'placeholder': 'Минимум 10 символов'
    }))

    class Meta:
        model = Review
        fields = ('rating', 'text')

    def clean_text(self):
        txt = self.cleaned_data.get('text', '')
        if txt and len(txt.strip()) < 10:
            raise forms.ValidationError('Минимальная длина отзыва — 10 символов.')
        return txt

    def clean_rating(self):
        val = self.cleaned_data.get('rating')
        try:
            d = Decimal(str(val))
        except Exception:
            raise forms.ValidationError('Некорректная оценка.')
        if d < Decimal('1.0') or d > Decimal('5.0'):
            raise forms.ValidationError('Оценка должна быть от 1.0 до 5.0.')
        # Разрешаем только шаг 0.5
        if (d * 2) % 1 != 0:
            raise forms.ValidationError('Шаг оценки — 0.5.')
        return d


class EmailOrUsernameAuthenticationForm(AuthenticationForm):
    """Allow users to log in using either username or email.

    The template can continue to render {{ form.username }} and {{ form.password }}.
    """

    def clean(self):
        username = self.data.get('username') or self.data.get(self.username_field)
        password = self.data.get('password')
        if username is None or password is None:
            return super().clean()

        UserModel = get_user_model()
        resolved_username = username
        try:
            # Try resolve by email OR username (case-insensitive)
            user_obj = (
                UserModel._default_manager.filter(Q(email__iexact=username) | Q(username__iexact=username))
                .only('username')
                .first()
            )
            if user_obj:
                resolved_username = getattr(user_obj, UserModel.USERNAME_FIELD, user_obj.username)
        except Exception:
            # Fallback to raw input
            resolved_username = username

        self.user_cache = authenticate(self.request, username=resolved_username, password=password)
        if self.user_cache is None:
            # reuse default error message/flow
            raise self.get_invalid_login_error()
        self.confirm_login_allowed(self.user_cache)
        self.cleaned_data = {'username': resolved_username, 'password': password}
        return self.cleaned_data
