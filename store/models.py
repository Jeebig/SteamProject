from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils.text import slugify
from django.utils import timezone


class Developer(models.Model):
    """
    Developer model: represents a game developer or studio.
    Fields:
        - name: Developer name (unique)
        - slug: URL-friendly identifier
        - appid: Optional Steam AppID
        - website: Official website
    """
    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    appid = models.IntegerField(null=True, blank=True, unique=True)
    website = models.URLField(blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Genre(models.Model):
    """
    Genre model: represents a game genre (Action, RPG, etc).
    Fields:
        - name: Genre name (unique)
        - slug: URL-friendly identifier
    """
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Game(models.Model):
    """
    Game model: main entity for store catalog.
    Fields:
        - title, slug, appid, description
        - price, original_price, discount_percent, currency
        - release_date, developer, genres
        - cover_image, screenshots, system requirements
    """
    CURRENCY_CHOICES = [
        ('USD', 'USD'),
        ('EUR', 'EUR'),
        ('UAH', 'UAH'),
        ('GBP', 'GBP'),
        ('RUB', 'RUB'),
        ('JPY', 'JPY'),
        ('CAD', 'CAD'),
        ('AUD', 'AUD'),
        ('CNY', 'CNY'),
        ('PLN', 'PLN'),
    ]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    appid = models.IntegerField(null=True, blank=True, unique=True, help_text="Steam AppID для превью header.jpg")
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    # Optional original price and discount percent for Steam-like price bands
    original_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    discount_percent = models.PositiveSmallIntegerField(default=0, help_text="Скидка в процентах, 0 если нет")
    currency = models.CharField(max_length=5, choices=CURRENCY_CHOICES, default='USD')
    release_date = models.DateField(null=True, blank=True)
    developer = models.ForeignKey(Developer, null=True, blank=True, on_delete=models.SET_NULL, related_name='games')
    genres = models.ManyToManyField(Genre, blank=True, related_name='games')
    cover_image = models.ImageField(upload_to='covers/', null=True, blank=True)
    # System requirements (raw HTML/Markdown or plain text). Single canonical declaration (duplicate removed).
    sysreq_min = models.TextField(
        blank=True,
        default='',
        help_text="Минимальные системные требования (можно HTML)"
    )
    sysreq_rec = models.TextField(
        blank=True,
        default='',
        help_text="Рекомендуемые системные требования (можно HTML)"
    )
    # Platform support flags
    supports_windows = models.BooleanField(default=False, help_text="Игра поддерживает Windows")
    supports_mac = models.BooleanField(default=False, help_text="Игра поддерживает macOS")
    supports_linux = models.BooleanField(default=False, help_text="Игра поддерживает Linux")
    # Homepage flags (filled by sync_steam_collections)
    is_top_seller = models.BooleanField(default=False)
    is_new_release = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class Screenshot(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='screenshots')
    image = models.ImageField(upload_to='screenshots/')
    caption = models.CharField(max_length=200, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.game.title} - {self.caption or self.image.name}"



# Корзина: отдельная модель для позиции в корзине
class CartItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cart_items')
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.game.title} x{self.quantity}"

# Заказ: связывает пользователя, игры, статус, сумму
class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Ожидание оплаты'),
        ('paid', 'Оплачен'),
        ('cancelled', 'Отменён'),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders')
    items = models.ManyToManyField(CartItem, related_name='orders')
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=5, choices=Game.CURRENCY_CHOICES, default='USD')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order #{self.id} by {self.user.username} ({self.status})"


class OrderItem(models.Model):
    """Позиция в заказе (снимок цены и количества на момент покупки)."""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items_snapshot')
    game = models.ForeignKey(Game, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=5, choices=Game.CURRENCY_CHOICES, default='USD')

    def line_total(self) -> Decimal:
        return (self.price or Decimal('0')) * Decimal(self.quantity or 1)

    def __str__(self):
        return f"{self.game.title} x{self.quantity} for Order #{self.order_id}"


class OwnedGame(models.Model):
    """Represents a game the user owns outside of store purchases (e.g., Steam sync).

    This decouples "library" from orders, allowing us to display external ownership
    without generating paid orders.
    """
    SOURCE_CHOICES = [
        ('steam', 'Steam'),
        ('manual', 'Manual'),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='owned_games')
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='owned_by')
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='steam')
    added_at = models.DateTimeField(auto_now_add=True)
    # Steam playtime stats (minutes) and last played timestamp
    playtime_forever = models.IntegerField(default=0, help_text="Минут всего по данным Steam")
    playtime_2weeks = models.IntegerField(null=True, blank=True, help_text="Минут за последние 2 недели")
    last_played = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('user', 'game', 'source')

    def __str__(self):
        return f"{self.user} owns {self.game} ({self.source})"

# Отзыв: пользователь, игра, текст, рейтинг
class Review(models.Model):
    """
    Review model: user review for a game.
    Fields:
        - user: author
        - game: reviewed game
        - text: review content
        - rating: score (1.0–5.0)
        - created_at: timestamp
    Constraints:
        - unique_together: one review per user/game
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews')
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='reviews')
    text = models.TextField(blank=True)
    rating = models.DecimalField(max_digits=2, decimal_places=1, default=Decimal('0.0'))
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = ('user', 'game')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['game', 'created_at']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.game.title} ({self.rating})"


class ReviewVote(models.Model):
    """
    ReviewVote model: marks a review as helpful/unhelpful.
    Fields:
        - review: target review
        - user: who voted
        - helpful: True/False
        - created_at: timestamp
    Constraints:
        - unique_together: one vote per user/review
    """
    """A single user's vote marking a review as helpful or not helpful.

    Unique per (review, user).
    """
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name='votes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='review_votes')
    helpful = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('review', 'user')

    def __str__(self):
        sign = '+' if self.helpful else '-'
        return f"{sign} vote on review"

# Профиль пользователя
class UserProfile(models.Model):
    """
    UserProfile: extended user info and preferences.
    Fields:
        - preferred_language, preferred_currency
        - privacy, comment privacy, friend request privacy
        - balance, total_spent, wishlist
        - avatar, steam_avatar, friend_code
    """
    LANG_CHOICES = [
        ('en', 'English'),
        ('uk', 'Українська'),
        ('ru', 'Русский'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    preferred_language = models.CharField(max_length=5, choices=LANG_CHOICES, default='en')
    preferred_currency = models.CharField(max_length=5, choices=Game.CURRENCY_CHOICES, default='USD')
    PRIVACY_CHOICES = [
        ('public', 'Публичный'),
        ('friends', 'Только друзья'),
        ('private', 'Только владелец'),
    ]
    privacy = models.CharField(max_length=10, choices=PRIVACY_CHOICES, default='public')
    # Дополнительные настройки приватности
    COMMENT_PRIVACY_CHOICES = [
        ('public', 'Комментировать могут все'),
        ('friends', 'Только друзья'),
        ('nobody', 'Никто, кроме меня'),
    ]
    FRIEND_REQUEST_PRIVACY_CHOICES = [
        ('public', 'Все могут отправлять заявки'),
        ('friends', 'Только друзья друзей (упрощённо — как все)'),
        ('nobody', 'Никто'),
    ]
    comment_privacy = models.CharField(max_length=10, choices=COMMENT_PRIVACY_CHOICES, default='public')
    friend_request_privacy = models.CharField(max_length=10, choices=FRIEND_REQUEST_PRIVACY_CHOICES, default='public')
    wishlist = models.ManyToManyField(Game, blank=True, related_name='wishlisted_by')
    # track how much the user has spent on the platform (used to determine limited accounts)
    total_spent = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    # Текущий баланс кошелька пользователя (в валюте preferred_currency на момент последнего обновления).
    # Храним единое число + currency_code = preferred_currency. При смене preferred_currency можно
    # по требованию пересчитать средствами вспомогательного метода (не автоматом, чтобы избежать
    # лишних конверсий). Максимум 2 знака после запятой.
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    steam_id = models.CharField(max_length=32, blank=True, help_text="SteamID64, если пользователь вошёл через Steam")
    steam_persona = models.CharField(max_length=200, blank=True)
    steam_avatar = models.URLField(blank=True)
    # Local avatar upload (overrides steam_avatar visually). Added to enable Steam-like profile customization.
    avatar = models.ImageField(upload_to='profiles/avatars/', null=True, blank=True)
    # Profile biography / about text (Markdown/plain supported)
    bio = models.TextField(blank=True, help_text="Краткое описание / 'О себе'")
    # Когда пользователь последний раз успешно менял username (для rate-limit)
    last_username_change = models.DateTimeField(null=True, blank=True, help_text="Timestamp последней успешной смены имени пользователя")
    # Accent theme color token (hex or predefined key) used for border/glow accents
    theme_color = models.CharField(max_length=20, blank=True, help_text="Цвет акцента профиля (#1b6b80 по умолчанию если пусто)")
    # Optional: preferred profile background tied to a Steam AppID header image
    bg_appid = models.IntegerField(null=True, blank=True, help_text="AppID игры для фонового баннера профиля (используется header.jpg)")
    # Optional: uploaded background image (has priority over bg_appid)
    profile_bg = models.ImageField(upload_to='profiles/backgrounds/', null=True, blank=True)
    # Последняя активность пользователя (обновляется middleware'ом)
    last_seen = models.DateTimeField(null=True, blank=True)
    # Настройки уведомлений
    notify_profile_comment = models.BooleanField(default=True, help_text="Внутренние уведомления о новых комментариях на моём профиле")
    notify_friend_request = models.BooleanField(default=True, help_text="Уведомления о входящих заявках в друзья")
    notify_friend_accept = models.BooleanField(default=True, help_text="Уведомления, когда мою заявку принимают")
    email_profile_comment = models.BooleanField(default=True, help_text="Присылать email о комментариях (если указан email)")
    email_friend_events = models.BooleanField(default=False, help_text="Email о запросах/подтверждениях дружбы")
    # Wishlist price drop alerts
    notify_price_drop = models.BooleanField(default=True, help_text="Уведомлять о снижении цены игр из списка желаемого")
    email_price_drop = models.BooleanField(default=False, help_text="Присылать email о снижении цены (если указан email)")
    # Публичный уникальный код для добавления в друзья (не зависит от username, стабильный).
    friend_code = models.CharField(max_length=16, unique=True, blank=True, null=True, help_text="Публичный код для добавления в друзья (вводится на странице 'Мои друзья')")

    def add_spending(self, amount):
        """Increase user's total_spent by Decimal amount and save."""
        try:
            amt = Decimal(amount)
        except Exception:
            return
        self.total_spent += amt
        self.save(update_fields=['total_spent'])

    # --- Wallet helpers ---
    def add_balance(self, amount, currency: str | None = None, save: bool = True):
        """Пополнить баланс.

        amount: число/строка/Decimal
        currency: код валюты суммы. Если отличается от preferred_currency – конвертируем.
        save: сразу сохранить модель.
        """
        from store.utils.currency import convert_amount  # локальный импорт, чтобы избежать циклов
        try:
            amt = Decimal(str(amount))
        except Exception:
            return
        if amt <= 0:
            return
        cur = currency or self.preferred_currency
        if cur != self.preferred_currency:
            try:
                amt = convert_amount(amt, cur, self.preferred_currency)
            except Exception:
                pass
        self.balance += amt
        if save:
            self.save(update_fields=['balance'])

    def deduct_balance(self, amount, currency: str | None = None, allow_negative: bool = False, save: bool = True) -> bool:
        """Списать сумму с баланса. Возвращает True при успехе.

        Если currency != preferred_currency произойдёт конвертация.
        allow_negative=False предотвращает уход в минус.
        """
        from store.utils.currency import convert_amount
        try:
            amt = Decimal(str(amount))
        except Exception:
            return False
        if amt <= 0:
            return False
        cur = currency or self.preferred_currency
        if cur != self.preferred_currency:
            try:
                amt = convert_amount(amt, cur, self.preferred_currency)
            except Exception:
                pass
        new_balance = self.balance - amt
        if not allow_negative and new_balance < Decimal('0.00'):
            return False
        self.balance = new_balance
        if save:
            self.save(update_fields=['balance'])
        return True

    def convert_balance(self, new_currency: str, save: bool = True):
        """Конвертировать текущий balance в новую валюту (используется при смене preferred_currency).

        Если новая валюта равна текущей preferred_currency – ничего не делает.
        """
        if new_currency == self.preferred_currency:
            return
        from store.utils.currency import convert_amount
        try:
            self.balance = convert_amount(self.balance, self.preferred_currency, new_currency)
        except Exception:
            pass
        old_currency = self.preferred_currency
        self.preferred_currency = new_currency
        if save:
            self.save(update_fields=['balance', 'preferred_currency'])

    @property
    def is_limited(self):
        """Legacy compatibility: account limitation disabled — always return False.

        We keep the property to avoid breaking templates or code that references it,
        but the platform no longer enforces a $5 spending limit.
        """
        return False

    def __str__(self):
        return f"Profile: {self.user.username}"

    # --- Friend code helpers ---
    @staticmethod
    def generate_friend_code(length: int = 10) -> str:
        """Сгенерировать псевдослучайный код (0-9A-Z), избегая двусмысленных символов.

        length: целевая длина.
        Возвращает строку, без гарантии уникальности (проверяется вызывающим кодом).
        """
        import secrets, string
        alphabet = ''.join([c for c in string.ascii_uppercase + string.digits if c not in {'O', '0', 'I', '1'}])
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    def ensure_friend_code(self):
        """Убедиться, что friend_code установлен. При коллизии пытается повторно.

        Максимум 10 попыток прежде чем сдаться (маловероятно при длине 10).
        """
        if self.friend_code:
            return self.friend_code
        attempts = 0
        while attempts < 10:
            code = self.generate_friend_code()
            if not UserProfile.objects.filter(friend_code=code).exists():
                self.friend_code = code
                try:
                    self.save(update_fields=['friend_code'])
                except Exception:
                    # Если редкая гонка – повторяем
                    attempts += 1
                    continue
                return code
            attempts += 1
        # Fallback: используем user.id в base36 (не самый красивый, но уникальный)
        try:
            base36 = ''
            n = int(self.user.id)
            chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
            if n == 0:
                base36 = '0'
            else:
                while n > 0:
                    n, r = divmod(n, 36)
                    base36 = chars[r] + base36
            self.friend_code = (base36 or 'U')[:16]
            self.save(update_fields=['friend_code'])
        except Exception:
            pass
        return self.friend_code

    def save(self, *args, **kwargs):
        # При первом сохранении профиля гарантируем наличие friend_code
        super().save(*args, **kwargs)
        if not self.friend_code:
            # Отдельно вызываем ensure после первичного сохранения, чтобы был доступен self.id / user.id
            try:
                self.ensure_friend_code()
            except Exception:
                pass


class WalletTransaction(models.Model):
    """История операций кошелька пользователя.

    amount: положительное число если зачисление, отрицательное если списание (в preferred_currency пользователя на момент операции).
    source_currency/source_amount: исходная введённая сумма (например, при пополнении в иной валюте) для прозрачности.
    kind: topup | purchase_deduct | manual_adjust | refund (зарезервировано).
    balance_after: баланс пользователя сразу после применения операции (в той же валюте, что и amount – preferred_currency).
    description: человеко-читаемое пояснение.
    created_at: время фиксации.
    """
    KIND_CHOICES = [
        ('topup', 'Пополнение'),
        ('purchase_deduct', 'Покупка'),
        ('manual_adjust', 'Корректировка'),
        ('refund', 'Возврат'),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet_transactions')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=5, choices=Game.CURRENCY_CHOICES, help_text="Валюта amount (preferred_currency пользователя).")
    source_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Исходная введённая сумма (если отличалась)")
    source_currency = models.CharField(max_length=5, choices=Game.CURRENCY_CHOICES, null=True, blank=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['user', 'kind']),
        ]

    def __str__(self):
        sign = '+' if self.amount >= 0 else '-'
        return f"{self.user} {sign}{abs(self.amount):.2f} {self.currency} ({self.kind})"


class SupportTicket(models.Model):
    STATUS_CHOICES = [
        ('new', 'Новая'),
        ('in_progress', 'В работе'),
        ('closed', 'Закрыта'),
    ]
    CATEGORY_CHOICES = [
        ('purchase', 'Проблема с покупкой/оплатой'),
        ('tech', 'Техническая проблема (загрузка, ошибки)'),
        ('account', 'Вопрос по аккаунту/профилю'),
        ('feedback', 'Обратная связь/предложение'),
        ('other', 'Другое'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='support_tickets')
    email = models.EmailField(blank=True)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='tech')
    category_other = models.CharField(max_length=200, blank=True, help_text="Если выбрано 'Другое' — уточните тему")
    subject = models.CharField(max_length=200)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        who = self.user.username if self.user else (self.email or 'anonymous')
        return f"[{self.get_status_display()}] {who}: {self.subject}"


class SupportMessage(models.Model):
    """Отдельные сообщения в рамках обращения в поддержку.

    Позволяет формировать переписку между пользователем и персоналом.
    Первое сообщение (оригинал обращения) дублируется из SupportTicket.message при создании тикета.
    """
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='messages')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='support_messages')
    is_staff = models.BooleanField(default=False, help_text="Сообщение отправлено сотрудником/администратором")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']  # хронологический порядок для удобства чтения

    def __str__(self):
        return f"Msg #{self.id} for Ticket #{self.ticket_id}"


class ProfileComment(models.Model):
    """Комментарий на странице профиля пользователя.

    profile_owner — владелец профиля, на чьей странице комментарий размещён.
    author — кто оставил комментарий.
    """
    profile_owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile_comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='authored_profile_comments')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['profile_owner', 'created_at']),
        ]

    def __str__(self):
        return f"Comment by {self.author} on {self.profile_owner}"


class Friendship(models.Model):
    """Симметричная дружба между двумя пользователями.

    Храним как упорядоченную пару (user_a_id < user_b_id), чтобы избежать дубликатов.
    """
    user_a = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='friendships_a')
    user_b = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='friendships_b')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user_a', 'user_b')
        indexes = [
            models.Index(fields=['user_a', 'user_b']),
        ]

    def save(self, *args, **kwargs):
        # гарантируем порядок (меньший id — user_a)
        if self.user_a_id and self.user_b_id and self.user_a_id > self.user_b_id:
            self.user_a_id, self.user_b_id = self.user_b_id, self.user_a_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Friendship({self.user_a} ↔ {self.user_b})"


class ProfileCommentSubscription(models.Model):
    """Подписка пользователя на комментарии на конкретном профиле."""
    subscriber = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile_comment_subs')
    profile_owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile_comment_followers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('subscriber', 'profile_owner')
        indexes = [
            models.Index(fields=['profile_owner', 'subscriber']),
        ]

    def __str__(self):
        return f"{self.subscriber} follows {self.profile_owner} comments"


class ProfileCommentBan(models.Model):
    """Бан пользователей в комментариях на определённом профиле."""
    profile_owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile_comment_bans')
    banned_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile_comment_banned_on')
    reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('profile_owner', 'banned_user')

    def __str__(self):
        return f"Ban {self.banned_user} on {self.profile_owner}"


class Notification(models.Model):
    """Внутреннее уведомление пользователя.

    kind: profile_comment, friend_request, friend_accept
    payload: произвольные данные для шаблона/ссылок
    link_url: куда перейти по клику
    """
    KIND_CHOICES = [
        ('profile_comment', 'Комментарий в профиле'),
        ('friend_request', 'Заявка в друзья'),
        ('friend_accept', 'Дружба подтверждена'),
        ('price_drop', 'Снижение цены в списке желаемого'),
        ('support_reply', 'Ответ поддержки'),
        ('support_new', 'Новое обращение в поддержку'),
        ('support_created', 'Создано ваше обращение'),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    payload = models.JSONField(default=dict, blank=True)
    link_url = models.CharField(max_length=300, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # TTL / auto-expire можно реализовать через периодическую задачу, пока просто поле для будущей чистки
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Когда уведомление можно авто-удалить")

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'is_read', 'created_at'])]

    def __str__(self):
        return f"Notify {self.user} {self.kind}"

    def mark_read(self):
        """Отметить уведомление прочитанным."""
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=['is_read'])

    @classmethod
    def bulk_mark_read(cls, user):
        """Быстро отметить все непрочитанные уведомления пользователя."""
        return cls.objects.filter(user=user, is_read=False).update(is_read=True)


class CurrencyRate(models.Model):
    """Хранит курс валюты base -> target.

    При обновлении API сохраняем свежие записи. Fallback логика читает
    последнюю запись по (base,target)."""
    base = models.CharField(max_length=5)
    target = models.CharField(max_length=5)
    rate = models.DecimalField(max_digits=18, decimal_places=8)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['base', 'target']),
            models.Index(fields=['fetched_at']),
        ]
        unique_together = ('base', 'target', 'fetched_at')

    def __str__(self):
        return f"{self.base}->{self.target}={self.rate} @ {self.fetched_at:%Y-%m-%d %H:%M}"

    @classmethod
    def latest_rate(cls, base: str, target: str):
        """Вернуть Decimal курса для самой свежей записи или None."""
        try:
            obj = (
                cls.objects
                .filter(base=base, target=target)
                .order_by('-fetched_at')
                .first()
            )
            return obj.rate if obj else None
        except Exception:
            return None


class PriceSnapshot(models.Model):
    """Ежедневный снимок цены игры для отслеживания изменений.

    Используется для уведомлений о снижении цены в вишлисте.
    """
    game = models.ForeignKey('Game', on_delete=models.CASCADE, related_name='price_snapshots')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=5, choices=Game.CURRENCY_CHOICES, default='USD')
    snapshot_date = models.DateField()

    class Meta:
        unique_together = ('game', 'snapshot_date')
        indexes = [
            models.Index(fields=['game', 'snapshot_date']),
        ]

    def __str__(self):
        return f"{self.game.title} {self.price} {self.currency} @ {self.snapshot_date}"


class FriendshipRequest(models.Model):
    """Запрос на дружбу (двухшаговая дружба)."""
    STATUS_CHOICES = [
        ('pending', 'Ожидает'),
        ('accepted', 'Принята'),
        ('rejected', 'Отклонена'),
        ('cancelled', 'Отменена'),
    ]
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='friend_requests_sent')
    receiver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='friend_requests_received')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('sender', 'receiver')
        indexes = [models.Index(fields=['receiver', 'status'])]

    def __str__(self):
        return f"FR {self.sender} -> {self.receiver} [{self.status}]"
