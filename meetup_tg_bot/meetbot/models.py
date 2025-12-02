from django.db import models


class Participant(models.Model):
    

    tg_id = models.BigIntegerField('Telegram user id', unique=True)
    tg_username = models.CharField('Ник в Telegram', max_length=64, blank=True)
    first_name = models.CharField('Имя', max_length=64, blank=True)
    last_name = models.CharField('Фамилия', max_length=64, blank=True)
    is_organizer = models.BooleanField('Организатор', default=False)
    is_speaker = models.BooleanField('Докладчик', default=False)
    wants_notifications = models.BooleanField('Получать уведомления', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        full_name = f'{self.first_name} {self.last_name}'.strip()
        if full_name:
            return full_name
        if self.tg_username:
            return f'@{self.tg_username}'
        return str(self.tg_id)


class Place(models.Model):
    

    name = models.CharField('Название площадки', max_length=100)
    address = models.CharField('Адрес', max_length=200, blank=True)
    description = models.TextField('Описание', blank=True)

    def __str__(self):
        return self.name


class Event(models.Model):
    

    name = models.CharField('Название мероприятия', max_length=150)
    description = models.TextField('Описание', blank=True)
    place = models.ForeignKey(
        Place,
        on_delete=models.SET_NULL,
        verbose_name='Место проведения',
        related_name='events',
        null=True,
        blank=True,
    )
    start_at = models.DateTimeField('Дата начала')
    end_at = models.DateTimeField('Дата окончания')
    is_active = models.BooleanField('Мероприятие активно', default=False)
    is_published = models.BooleanField('Опубликовано', default=False)
    announcements_enabled = models.BooleanField('Рассылки включены', default=True)
    current_talk = models.ForeignKey(
        'Talk',
        verbose_name='Текущий доклад',
        related_name='+',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class TalkStatus(models.TextChoices):
    SCHEDULED = 'scheduled', 'Запланировано'
    IN_PROGRESS = 'in_progress', 'В процессе'
    DONE = 'done', 'Завершено'
    CANCELLED = 'cancelled', 'Отменено'


class Talk(models.Model):
    """Отдельный доклад в программе митапа."""

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='talks',
        verbose_name='Мероприятие',
    )
    title = models.CharField('Название доклада', max_length=200)
    description = models.TextField('Описание', blank=True)
    speaker = models.ForeignKey(
        Participant,
        on_delete=models.SET_NULL,
        related_name='talks',
        verbose_name='Докладчик',
        null=True,
        blank=True,
    )
    start_at = models.DateTimeField('Начало доклада')
    end_at = models.DateTimeField('Конец доклада')
    order = models.PositiveIntegerField('Порядок в программе', default=0)
    room = models.CharField('Зал/комната', max_length=64, blank=True)
    status = models.CharField(
        'Статус',
        max_length=20,
        choices=TalkStatus.choices,
        default=TalkStatus.SCHEDULED,
    )
    is_current = models.BooleanField('Текущий доклад', default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['event_id', 'order', 'start_at']

    def __str__(self):
        return f'{self.event}: {self.title}'


class QuestionStatus(models.TextChoices):
    PENDING = 'pending', 'Получен'
    SENT_TO_SPEAKER = 'sent', 'Отправлен спикеру'
    ANSWERED = 'answered', 'Отвечен'
    REJECTED = 'rejected', 'Отклонён'


class Question(models.Model):
    

    author = models.ForeignKey(
        Participant,
        on_delete=models.SET_NULL,
        verbose_name='Автор вопроса',
        related_name='questions',
        null=True,
        blank=True,
    )
    talk = models.ForeignKey(
        Talk,
        on_delete=models.CASCADE,
        verbose_name='Доклад',
        related_name='questions',
    )
    text = models.CharField('Вопрос', max_length=500)
    status = models.CharField(
        'Статус',
        max_length=20,
        choices=QuestionStatus.choices,
        default=QuestionStatus.PENDING,
    )
    answer_text = models.TextField('Ответ спикера', blank=True)
    asked_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    speaker_message_id = models.BigIntegerField(
        'ID сообщения в чате спикера',
        null=True,
        blank=True,
    )
    attendee_message_id = models.BigIntegerField(
        'ID сообщения для автора',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['-asked_at']

    def __str__(self):
        return f'{self.talk}: {self.text[:50]}'


class NetworkingProfile(models.Model):
    """Анкета участника."""

    participant = models.ForeignKey(
        Participant,
        on_delete=models.CASCADE,
        related_name='networking_profiles',
        verbose_name='Участник',
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='networking_profiles',
        verbose_name='Мероприятие',
    )
    role = models.CharField('Роль', max_length=64, blank=True)
    company = models.CharField('Компания', max_length=128, blank=True)
    stack = models.CharField('Технический стек', max_length=255, blank=True)
    interests = models.TextField('Интересы', blank=True)
    goals = models.TextField('Цель знакомства', blank=True)
    contact = models.CharField(
        'Контакт в Telegram',
        max_length=128,
        help_text='@username или ссылка',
    )
    is_active = models.BooleanField('Активна', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('participant', 'event')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.participant} ({self.role})'


class NetworkingMatchStatus(models.TextChoices):
    PENDING = 'pending', 'Отправлено'
    ACCEPTED = 'accepted', 'Принято'
    SKIPPED = 'skipped', 'Пропущено'


class NetworkingMatch(models.Model):
    """Выданная пара для мэтча."""

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='networking_matches',
        verbose_name='Мероприятие',
    )
    source_profile = models.ForeignKey(
        NetworkingProfile,
        on_delete=models.CASCADE,
        related_name='sent_matches',
        verbose_name='Анкета инициатора',
    )
    target_profile = models.ForeignKey(
        NetworkingProfile,
        on_delete=models.CASCADE,
        related_name='received_matches',
        verbose_name='Предложенная анкета',
    )
    status = models.CharField(
        'Статус',
        max_length=16,
        choices=NetworkingMatchStatus.choices,
        default=NetworkingMatchStatus.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('event', 'source_profile', 'target_profile')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.source_profile} -> {self.target_profile} ({self.status})'


class DonationStatus(models.TextChoices):
    PENDING = 'pending', 'Ожидает'
    WAITING_FOR_CAPTURE = 'waiting_for_capture', 'Ожидает подтверждения'
    SUCCEEDED = 'succeeded', 'Успешно'
    FAILED = 'failed', 'Неуспешно'
    CANCELED = 'canceled', 'Отменено'


class Donation(models.Model):
   

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='donations',
        verbose_name='Мероприятие',
    )
    participant = models.ForeignKey(
        Participant,
        on_delete=models.SET_NULL,
        related_name='donations',
        verbose_name='Отправитель',
        null=True,
        blank=True,
    )
    amount = models.DecimalField('Сумма', max_digits=10, decimal_places=2)
    currency = models.CharField('Валюта', max_length=8, default='RUB')
    status = models.CharField(
        'Статус',
        max_length=32,
        choices=DonationStatus.choices,
        default=DonationStatus.PENDING,
    )
    provider = models.CharField('Провайдер', max_length=50, default='yookassa', blank=True)
    yookassa_payment_id = models.CharField(
        'ID платежа YooKassa',
        max_length=64,
        blank=True,
        help_text='payment.id из ответа YooKassa',
    )
    idempotence_key = models.CharField(
        'Idempotence-Key',
        max_length=64,
        blank=True,
        help_text='для повторных запросов create/capture',
    )
    confirmation_url = models.CharField(
        'Ссылка для оплаты',
        max_length=500,
        blank=True,
    )
    description = models.CharField('Назначение платежа', max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.amount} {self.currency} ({self.status})'


class SubscriptionType(models.TextChoices):
    EVENT = 'event', 'Обновления мероприятия'
    FUTURE = 'future', 'Будущие мероприятия'


class Subscription(models.Model):
   

    participant = models.ForeignKey(
        Participant,
        on_delete=models.CASCADE,
        related_name='subscriptions',
        verbose_name='Участник',
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='subscriptions',
        verbose_name='Мероприятие',
        null=True,
        blank=True,
    )
    subscription_type = models.CharField(
        'Тип подписки',
        max_length=16,
        choices=SubscriptionType.choices,
        default=SubscriptionType.EVENT,
    )
    is_active = models.BooleanField('Активна', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('participant', 'event', 'subscription_type')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.participant} -> {self.subscription_type}'


class SpeakerApplicationStatus(models.TextChoices):
    NEW = 'new', 'Новая'
    REVIEWED = 'reviewed', 'Рассмотрена'


class SpeakerApplication(models.Model):
    participant = models.ForeignKey(
        Participant,
        on_delete=models.SET_NULL,
        verbose_name='Заявитель',
        related_name='speaker_applications',
        null=True,
        blank=True,
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.SET_NULL,
        related_name='speaker_applications',
        verbose_name='Событие',
        null=True,
        blank=True,
    )
    topic = models.TextField('Тема доклада')
    contact = models.CharField('Контакт', max_length=255)
    status = models.CharField(
        'Статус',
        max_length=16,
        choices=SpeakerApplicationStatus.choices,
        default=SpeakerApplicationStatus.NEW,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.topic[:30]} ({self.status})'
