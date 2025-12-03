from telegram import Update
from asgiref.sync import sync_to_async
from django.apps import apps

import logging

from django.utils import timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler
from meetbot.models import (
    Event,
    NetworkingMatch,
    NetworkingProfile,
    Participant,
    QuestionStatus,
    Talk,
    DonationStatus,
    Donation,
    Subscription,
    SubscriptionType,
    SpeakerApplication,
)
from meetbot.services.networking import (
    create_match,
    get_next_match,
    get_or_create_profile,
    get_waiting_profile,
    mark_match_status,
)
from meetbot.services.donations import create_donation, create_yookassa_payment, refresh_payment_status
from meetbot.services.talks import create_question, finish_talk, get_current_talk, get_next_talk, start_talk

from meetbot.bot.constants import (
    CB_MAIN_MENU,
    CB_NETWORKING,
    CB_PROGRAM,
    CB_SPEAKER_MENU,
    CB_QUESTION,
    CB_DONATE,
    CB_SUBSCRIBE,
    CB_ORGANIZER_MENU,
    CB_DONATIONS,
    CB_SPEAKER_APPLY,
    CB_NETWORK_SEARCH,
    CB_NETWORK_START,
    CB_DONATE_PAY_PREFIX,
    CB_DONATE_STATUS_PREFIX,
    CB_TALK_START_PREFIX,
    CB_TALK_FINISH_PREFIX,
    CB_MATCH_ACCEPT,
    CB_MATCH_SKIP,
    CB_MATCH_STOP,
)


@sync_to_async
def get_unpublished_events():
    event = apps.get_model('meetbot', 'Event')
    return list(
        event.objects.filter(is_published=False).order_by('start_at')
    )


def format_local(dt):
    if not dt:
        return ""
    tz = timezone.get_current_timezone()
    return dt.astimezone(tz).strftime('%H:%M')


async def _finish_talk_async(talk: Talk) -> Talk:
    return await sync_to_async(finish_talk, thread_sensitive=True)(talk)


async def _start_talk_async(talk: Talk) -> Talk:
    return await sync_to_async(start_talk, thread_sensitive=True)(talk)


async def _has_speaker_talk_async(participant: Participant, event: Event) -> bool:
    return await sync_to_async(
        lambda: event.talks.filter(speaker=participant).exists(),
        thread_sensitive=True,
    )()


async def _count_pending_questions_async(talk: Talk) -> int:
    return await sync_to_async(
        lambda: talk.questions.filter(status=QuestionStatus.PENDING).count(),
        thread_sensitive=True,
    )()


async def _question_stats_async(talk: Talk):
    def _calc():
        qs = talk.questions.all()
        total = qs.count()
        answered = qs.filter(status=QuestionStatus.ANSWERED).count()
        rejected = qs.filter(status=QuestionStatus.REJECTED).count()
        pending = qs.filter(status=QuestionStatus.PENDING).count()
        return total, answered, rejected, pending

    return await sync_to_async(_calc, thread_sensitive=True)()


async def _list_event_talks_async(event: Event):
    return await sync_to_async(
        lambda: list(event.talks.select_related('speaker').order_by('start_at')),
        thread_sensitive=True
    )()


async def _get_talk_by_id_async(talk_id: int) -> Talk | None:
    return await sync_to_async(
        lambda: Talk.objects.select_related('speaker').filter(id=talk_id).first(),
        thread_sensitive=True
    )()


async def _get_event_by_id_async(event_id: int) -> Event | None:
    if not event_id:
        return None
    return await sync_to_async(lambda: Event.objects.filter(id=event_id).first(), thread_sensitive=True)()


async def _attach_speaker_flag_async(participant: Participant | None, event: Event | None) -> Participant | None:
    """Помечает участника как спикера для меню, если он привязан к докладу активного события."""
    if not (participant and event):
        return participant
    has_talk = await _has_speaker_talk_async(participant, event)
    if has_talk:
        participant._has_speaker_talk = True  # noqa: SLF001
    return participant


async def _get_current_talk_async(event: Event) -> Talk | None:
    return await sync_to_async(get_current_talk, thread_sensitive=True)(event)


async def _get_active_event_async() -> Event | None:
    return await sync_to_async(lambda: Event.objects.filter(is_active=True).order_by('-start_at').first(),
                               thread_sensitive=True)()


async def _reply(update: Update, text: str, show_menu: bool = False, participant: Participant | None = None) -> None:
    """message или callback"""
    markup = None
    if show_menu:
        if participant is None:
            participant = await _ensure_participant_async(update)
        event = await _get_active_event_async()
        participant = await _attach_speaker_flag_async(participant, event)
        markup = _menu_keyboard(participant)
    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=markup,
            parse_mode='Markdown'
        )
    elif update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                text,
                reply_markup=markup,
                parse_mode='Markdown'
            )
        except Exception:
            await update.callback_query.message.reply_text(
                text,
                reply_markup=markup,
                parse_mode='Markdown'
            )


def _ensure_participant(update: Update) -> Participant | None:
    tg_user = update.effective_user
    if not tg_user:
        return None
    participant, _ = Participant.objects.get_or_create(
        tg_id=tg_user.id,
        defaults={
            'tg_username': tg_user.username or '',
            'first_name': tg_user.first_name or '',
            'last_name': tg_user.last_name or '',
        },
    )
    return participant


async def _ensure_participant_async(update: Update) -> Participant | None:
    return await (sync_to_async(
        _ensure_participant,
        thread_sensitive=True
    )(update))


async def _send_with_markup(update: Update, text: str, reply_markup) -> None:
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        except Exception:
            await update.callback_query.message.reply_text(text, reply_markup=reply_markup)


def _parse_id_from_callback(update: Update, prefix: str) -> int | None:
    query = update.callback_query
    if not query or not query.data or not query.data.startswith(prefix):
        return None
    try:
        return int(query.data.replace(prefix, '', 1))
    except ValueError:
        return None


async def _get_next_event_async() -> Event | None:
    return await sync_to_async(
        lambda: Event.objects.filter(start_at__gt=timezone.now()).order_by('start_at').first(),
        thread_sensitive=True,
    )()


async def _get_profile_async(participant: Participant, event: Event) -> NetworkingProfile | None:
    return await sync_to_async(
        lambda: NetworkingProfile.objects.filter(participant=participant, event=event, is_active=True).first(),
        thread_sensitive=True,
    )()


async def _get_next_talk_async(event: Event) -> Talk | None:
    return await sync_to_async(get_next_talk, thread_sensitive=True)(event)


async def _has_profile_async(participant: Participant, event: Event) -> bool:
    return await sync_to_async(
        lambda: NetworkingProfile.objects.filter(participant=participant, event=event, is_active=True).exists(),
        thread_sensitive=True,
    )()


async def _send_match_card(update: Update, target, match) -> None:
    text = (
        f"Кандидат:\n"
        f"Роль: {target.role}\n"
        f"Компания: {target.company}\n"
        f"Стек: {target.stack}\n"
        f"Интересы: {target.interests}\n"
        f"Контакт: {target.contact}\n"
        f"Как поступить?"
    )
    buttons = [
        [InlineKeyboardButton('Связаться', callback_data=CB_MATCH_ACCEPT)],
        [InlineKeyboardButton('Дальше', callback_data=CB_MATCH_SKIP)],
        [InlineKeyboardButton('Стоп', callback_data=CB_MATCH_STOP)],
    ]
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


def _search_end_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton('Попробовать ещё', callback_data=CB_NETWORK_SEARCH)],
            [InlineKeyboardButton('Главное меню', callback_data=CB_MAIN_MENU)],
        ]
    )


async def _send_search_menu(update: Update, text: str) -> None:
    if update.message:
        await update.message.reply_text(text, reply_markup=_search_end_markup())
    elif update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(text, reply_markup=_search_end_markup())
        except Exception:
            await update.callback_query.message.reply_text(text, reply_markup=_search_end_markup())


def _get_current_match(context: ContextTypes.DEFAULT_TYPE) -> NetworkingMatch | None:
    match_id = context.user_data.get('current_match_id')
    if not match_id:
        return None
    try:
        return NetworkingMatch.objects.select_related('source_profile', 'target_profile').get(id=match_id)
    except NetworkingMatch.DoesNotExist:
        return None


async def _get_or_create_profile_async(**kwargs) -> NetworkingProfile:
    return await sync_to_async(get_or_create_profile, thread_sensitive=True)(**kwargs)


async def _get_next_match_async(profile: NetworkingProfile) -> NetworkingProfile | None:
    return await sync_to_async(get_next_match, thread_sensitive=True)(profile)


async def _create_match_async(**kwargs) -> NetworkingMatch:
    return await sync_to_async(create_match, thread_sensitive=True)(**kwargs)


async def _mark_match_status_async(match: NetworkingMatch, status: str) -> NetworkingMatch:
    return await sync_to_async(mark_match_status, thread_sensitive=True)(match, status)


async def _notify_waiting_async(profile: NetworkingProfile, bot) -> None:
    waiting = await sync_to_async(get_waiting_profile, thread_sensitive=True)(profile)
    if not waiting:
        return
    match = await _create_match_async(source_profile=waiting, target_profile=profile)
    text = (
        f"Нашёлся собеседник!\n"
        f"Роль: {profile.role}\n"
        f"Компания: {profile.company}\n"
        f"Стек: {profile.stack}\n"
        f"Интересы: {profile.interests}\n"
        f"Контакт: {profile.contact}\n"
        "Если хотите пообщаться — нажмите /networking."
    )
    try:
        await bot.send_message(chat_id=waiting.participant.tg_id, text=text)
    except Exception:
        pass


async def _get_current_match_async(context: ContextTypes.DEFAULT_TYPE) -> NetworkingMatch | None:
    return await sync_to_async(_get_current_match, thread_sensitive=True)(context)


async def _start_matching(profile: NetworkingProfile, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    target = await _get_next_match_async(profile)
    if not target:
        await _send_search_menu(
            update,
            'Пока нет анкет, чтобы познакомить. Как появятся новые — напомню. Можно вернуться в меню или попробовать позже.',
        )
        await _notify_waiting_async(profile, context.application.bot)
        return ConversationHandler.END
    match = await _create_match_async(source_profile=profile, target_profile=target)
    context.user_data['current_match_id'] = match.id
    await _send_match_card(update, target, match)
    return BotState.NETWORKING_MATCH


async def _create_question_async(**kwargs):
    return await sync_to_async(create_question, thread_sensitive=True)(**kwargs)


async def _notify_speaker_async(question, bot) -> bool:
    talk = question.talk
    speaker = talk.speaker
    if not (speaker and speaker.tg_id):
        return False

    author = question.author
    author_name = 'Аноним'
    if author:
        parts = [author.first_name, author.last_name]
        fallback_name = ' '.join([p for p in parts if p]).strip()
        if author.tg_username:
            author_name = f"@{author.tg_username}"
        elif fallback_name:
            author_name = fallback_name
    text = (
        f"Вопрос к вашему докладу:\n"
        f"{talk.title}\n\n"
        f"{question.text}\n\n"
        f"От: {author_name}"
    )
    try:
        await bot.send_message(chat_id=speaker.tg_id, text=text)
        return True
    except Exception:
        return False


async def _set_question_status_async(question, status: str) -> None:
    def _set_status(q, s):
        q.status = s
        q.save(update_fields=['status'])

    await sync_to_async(_set_status, thread_sensitive=True)(question, status)


async def _list_speaker_talks_async(participant: Participant, event: Event):
    return await sync_to_async(
        lambda: list(
            event.talks.select_related('speaker')
            .filter(speaker=participant)
            .order_by('start_at')
        ),
        thread_sensitive=True,
    )()


async def _finish_talk_async(talk: Talk) -> Talk:
    return await sync_to_async(finish_talk, thread_sensitive=True)(talk)


async def _list_notification_participants_async():
    return await sync_to_async(
        lambda: list(Participant.objects.filter(wants_notifications=True)),
        thread_sensitive=True,
    )()


def _parse_amount_from_callback(update: Update, prefix: str) -> float | None:
    value = _parse_id_from_callback(update, prefix)
    if value is None:
        return None
    return float(value)


async def _create_donation_async(participant, event, amount, description):
    from decimal import Decimal

    return await sync_to_async(create_donation, thread_sensitive=True)(
        participant=participant,
        event=event,
        amount=Decimal(str(amount)),
        description=description,
    )


async def _create_yookassa_payment_async(donation):
    return await sync_to_async(create_yookassa_payment, thread_sensitive=True)(donation)


async def _get_donation_by_id_async(donation_id: int):
    return await sync_to_async(
        lambda: Donation.objects.filter(id=donation_id).select_related('participant', 'event').first(),
        thread_sensitive=True,
    )()


async def _refresh_payment_async(donation):
    return await sync_to_async(refresh_payment_status, thread_sensitive=True)(donation)


async def _has_subscription_async(participant: Participant, event: Event | None, sub_type: str) -> bool:
    return await sync_to_async(
        lambda: Subscription.objects.filter(
            participant=participant,
            event=event if sub_type == SubscriptionType.EVENT else None,
            subscription_type=sub_type,
            is_active=True,
        ).exists(),
        thread_sensitive=True,
    )()


async def _toggle_subscription_async(participant: Participant, event: Event | None, sub_type: str) -> bool:
    def _toggle():
        sub, _ = Subscription.objects.get_or_create(
            participant=participant,
            event=event if sub_type == SubscriptionType.EVENT else None,
            subscription_type=sub_type,
            defaults={'is_active': True},
        )
        sub.is_active = not sub.is_active if sub.id else True
        sub.save(update_fields=['is_active'])
        return sub.is_active

    return await sync_to_async(_toggle, thread_sensitive=True)()


def _donation_markup(donation: Donation) -> InlineKeyboardMarkup:
    buttons = []
    if donation.confirmation_url:
        buttons.append([InlineKeyboardButton('Оплатить', url=donation.confirmation_url)])
    buttons.append(
        [InlineKeyboardButton('Проверить статус', callback_data=f'{CB_DONATE_STATUS_PREFIX}{donation.id}')]
    )
    buttons.append([InlineKeyboardButton('Главное меню', callback_data=CB_MAIN_MENU)])
    return InlineKeyboardMarkup(buttons)


async def _donations_summary_async(event: Event):
    def _summary():
        qs = Donation.objects.filter(event=event).order_by('-created_at')
        total = sum(d.amount for d in qs if d.status == DonationStatus.SUCCEEDED)
        items = []
        for d in qs[:5]:
            who = d.participant or f'#{d.id}'
            items.append(
                {
                    'amount': d.amount,
                    'status': d.status,
                    'who': who,
                }
            )
        return {'total': total, 'count': qs.count(), 'items': items}

    return await sync_to_async(_summary, thread_sensitive=True)()


async def _list_subscribers_async(event: Event | None):
    def _subs():
        qs = Subscription.objects.filter(is_active=True)
        if event:
            qs = qs.filter(subscription_type__in=[SubscriptionType.EVENT, SubscriptionType.FUTURE]).filter(
                models.Q(event=event) | models.Q(subscription_type=SubscriptionType.FUTURE)
            )
        else:
            qs = qs.filter(subscription_type=SubscriptionType.FUTURE)
        participant_ids = qs.values_list('participant_id', flat=True)
        return Participant.objects.filter(id__in=participant_ids)

    from django.db import models

    return await sync_to_async(lambda: list(_subs()), thread_sensitive=True)()


async def _list_organizers_async():
    return await sync_to_async(lambda: list(Participant.objects.filter(is_organizer=True)), thread_sensitive=True)()


async def _get_subscribed_event_async() -> Event | None:
    def _latest():
        from django.db import models
        ev_ids = (
            Subscription.objects.filter(is_active=True, subscription_type=SubscriptionType.EVENT)
            .values_list('event_id', flat=True)
            .distinct()
        )
        return Event.objects.filter(id__in=ev_ids).order_by('-start_at').first()

    return await sync_to_async(_latest, thread_sensitive=True)()


async def _create_speaker_application_async(participant: Participant | None, event: Event | None, topic: str,
                                            contact: str):
    return await sync_to_async(
        lambda: SpeakerApplication.objects.create(
            participant=participant,
            event=event,
            topic=topic,
            contact=contact,
        ),
        thread_sensitive=True,
    )()


def _menu_keyboard(participant: Participant | None = None) -> InlineKeyboardMarkup:
    is_speaker = False
    is_organizer = False
    if participant:
        is_speaker = participant.is_speaker or getattr(participant, '_has_speaker_talk', False)
        is_organizer = participant.is_organizer
    buttons = [
        [
            InlineKeyboardButton('📅 Программа', callback_data=CB_PROGRAM),
            InlineKeyboardButton('❓ Вопрос спикеру', callback_data=CB_QUESTION),
        ],
        [
            InlineKeyboardButton('🤝 Познакомиться', callback_data=CB_NETWORKING),
            InlineKeyboardButton('💸 Донат', callback_data=CB_DONATE),
        ],
        [InlineKeyboardButton('🔔 Подписка', callback_data=CB_SUBSCRIBE)],
    ]
    if is_speaker:
        buttons.append([InlineKeyboardButton('🎤 Панель докладчика', callback_data=CB_SPEAKER_MENU)])
    if is_organizer:
        buttons.append([InlineKeyboardButton('🛠 Панель организатора', callback_data=CB_ORGANIZER_MENU)])
    buttons.append([InlineKeyboardButton('🎙 Хочу быть спикером', callback_data=CB_SPEAKER_APPLY)])
    return InlineKeyboardMarkup(buttons)
