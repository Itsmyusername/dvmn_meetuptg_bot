import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from asgiref.sync import sync_to_async
from meetbot.models import Event, NetworkingMatch, NetworkingMatchStatus, NetworkingProfile, Participant
from meetbot.services.networking import (
    count_profiles_for_event,
    create_match,
    get_next_match,
    get_or_create_profile,
    get_waiting_profile,
    mark_match_status,
)

from .constants import (
    CB_DONATE,
    CB_MAIN_MENU,
    CB_NETWORKING,
    CB_NETWORK_START,
    CB_NETWORK_SEARCH,
    CB_PROGRAM,
    CB_QUESTION,
    CB_SUBSCRIBE,
    CB_MATCH_ACCEPT,
    CB_MATCH_SKIP,
    CB_MATCH_STOP,
    CMD_ASK,
    CMD_CANCEL,
    CMD_DONATE,
    CMD_HEALTH,
    CMD_NETWORKING,
    CMD_PROGRAM,
    CMD_START,
    CMD_SUBSCRIBE,
    BotState,
)

logger = logging.getLogger(__name__)


def _menu_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton('📅 Программа', callback_data=CB_PROGRAM),
            InlineKeyboardButton('❓ Вопрос спикеру', callback_data=CB_QUESTION),
        ],
        [
            InlineKeyboardButton('🤝 Познакомиться', callback_data=CB_NETWORKING),
            InlineKeyboardButton('🍕 Донат', callback_data=CB_DONATE),
        ],
        [InlineKeyboardButton('🔔 Подписка', callback_data=CB_SUBSCRIBE)],
    ]
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Стартовая команда"""
    participant = await _ensure_participant_async(update)
    role_hint = 'Гость'
    if participant:
        if participant.is_organizer:
            role_hint = 'Организатор'
        elif participant.is_speaker:
            role_hint = 'Докладчик'

    text = (
        'Привет! Я бот Python Meetup.\n'
        '• Задавайте вопросы спикерам во время доклада\n'
        '• Смотрите программу и что идет дальше\n'
        '• Познакомьтесь с участниками и поддержите митап донатом\n'
        f'Вы зашли как: {role_hint}'
    )

    await _reply(update, text, show_menu=True)


async def program(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ensure_participant_async(update)
    await _reply(update, 'Скоро покажу программу и текущий доклад.', show_menu=True)


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ensure_participant_async(update)
    await _reply(update, 'Здесь появится форма для вопроса текущему спикеру.', show_menu=True)


async def networking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    event = await _get_active_event_async()
    has_profile = False
    profile = None
    if participant and event:
        profile = await _get_profile_async(participant, event)
        has_profile = profile is not None

    text = (
        'Познакомимся:\n'
        '1) Заполните короткую анкету\n'
        '2) Получите анкету собеседника\n'
        '3) Кнопки: “Связаться”, “Дальше”, “Стоп”\n'
        '4) Если вы первый, бот напомнит, когда появятся новые анкеты'
    )

    buttons = [[InlineKeyboardButton('Заполнить анкету', callback_data=CB_NETWORK_START)]]
    if has_profile:
        buttons = [
            [
                InlineKeyboardButton('Изменить анкету', callback_data=CB_NETWORK_START),
                InlineKeyboardButton('Начать знакомство', callback_data=CB_NETWORK_SEARCH),
            ]
        ]
        profile_text = (
            f"Ваша анкета:\n"
            f"Роль: {profile.role}\n"
            f"Компания: {profile.company}\n"
            f"Стек: {profile.stack}\n"
            f"Интересы: {profile.interests}\n"
            f"Контакт: {profile.contact}"
        )
        text = profile_text

    markup = InlineKeyboardMarkup(buttons)
    if update.message:
        await update.message.reply_text(text, reply_markup=markup)
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=markup)


async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ensure_participant_async(update)
    await _reply(update, 'Добавим кнопку доната и покажем, как поддержать митап.', show_menu=True)


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ensure_participant_async(update)
    await _reply(update, 'Настроим подписку на обновления и будущие события.', show_menu=True)


async def health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, 'ok', show_menu=False)


async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ответы на кнопки главного меню (заглушки)."""
    query = update.callback_query
    if not query:
        return
    logger.info('Menu callback received: %s', query.data)

    callbacks = {
        CB_PROGRAM: program,
        CB_QUESTION: ask,
        CB_MAIN_MENU: start,
        CB_NETWORKING: networking,
        CB_DONATE: donate,
        CB_SUBSCRIBE: subscribe,
    }
    handler = callbacks.get(query.data)
    if handler:
        await handler(update, context)
        return

    await query.answer()
    await query.edit_message_text('Команда в разработке.', reply_markup=_menu_keyboard())


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка неизвестных команд."""
    message_text = update.message.text if update.message else 'n/a'
    logger.debug('Unknown command: %s', message_text)
    if update.message:
        await update.message.reply_text('Не понял команду. Используйте /start.')


async def ask_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Старт сбора вопроса."""
    await _reply(update, 'Введите текст вопроса для текущего спикера. /cancel для отмены.', show_menu=False)
    return BotState.ASK_TEXT


async def ask_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохранение вопроса (заглушка)."""
    question_text = update.message.text if update.message else ''
    context.user_data['question_text'] = question_text
    await update.message.reply_text('Спасибо! Вопрос передадим спикеру. /start')
    return ConversationHandler.END


async def networking_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # если нажали "Начать знакомство" с уже сохранённой анкетой — сразу показываем карточку
    if update.callback_query and update.callback_query.data == CB_NETWORK_SEARCH:
        participant = await _ensure_participant_async(update)
        event = await _get_active_event_async()
        if not (participant and event):
            await _reply(update, 'Нет активного мероприятия. Попробуйте позже.', show_menu=True)
            return ConversationHandler.END
        profile = await _get_profile_async(participant, event)
        if not profile:
            await _reply(update, 'Анкета не найдена. Заполните её сначала.', show_menu=True)
            return ConversationHandler.END
        return await _start_matching(profile, update, context)

    await _reply(update, 'Кто вы по роли? (например, backend, data, PM). /cancel для отмены.', show_menu=False)
    return BotState.NETWORKING_ROLE


async def networking_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['role'] = update.message.text
    await update.message.reply_text('Где работаете? (компания/команда).')
    return BotState.NETWORKING_COMPANY


async def networking_company(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['company'] = update.message.text
    await update.message.reply_text('Какой ваш стек или ключевые технологии?')
    return BotState.NETWORKING_STACK


async def networking_stack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['stack'] = update.message.text
    await update.message.reply_text('Ваши интересы/темы для обсуждения?')
    return BotState.NETWORKING_INTERESTS


async def networking_interests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['interests'] = update.message.text
    await update.message.reply_text('Оставьте контакт в Telegram (@username).')
    return BotState.NETWORKING_CONTACT


async def networking_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['contact'] = update.message.text
    user = await _ensure_participant_async(update)
    event = await _get_active_event_async()
    if not user or not event:
        await update.message.reply_text('Нет активного мероприятия. Попробуйте позже.')
        return ConversationHandler.END

    profile = await _get_or_create_profile_async(
        participant=user,
        event=event,
        role=context.user_data.get('role', ''),
        company=context.user_data.get('company', ''),
        stack=context.user_data.get('stack', ''),
        interests=context.user_data.get('interests', ''),
        contact=context.user_data.get('contact', ''),
    )
    await update.message.reply_text(
        f"Анкета сохранена:\n"
        f"Роль: {profile.role}\n"
        f"Компания: {profile.company}\n"
        f"Стек: {profile.stack}\n"
        f"Интересы: {profile.interests}\n"
        f"Контакт: {profile.contact}\n"
        "Ищу для вас собеседника..."
    )

    target = await _get_next_match_async(profile)
    if not target:
        await _send_search_menu(
            update,
            'Вы первый в очереди. Напомню, когда появится ещё анкета.\nМожно вернуться в меню или попробовать поиск позже.',
        )
        await _notify_waiting_async(profile, context.application.bot)
        return ConversationHandler.END

    match = await _create_match_async(source_profile=profile, target_profile=target)
    context.user_data['current_match_id'] = match.id
    await _send_match_card(update, target, match)
    await _notify_waiting_async(profile, context.application.bot)
    return BotState.NETWORKING_MATCH


async def donate_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _reply(update, 'Введите сумму доната в рублях. /cancel для отмены.')
    return BotState.DONATE_AMOUNT


async def donate_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    amount_text = update.message.text.strip()
    context.user_data['donate_amount'] = amount_text
    await update.message.reply_text(
        f'Готовим ссылку на оплату на {amount_text} RUB (заглушка). Спасибо за поддержку!'
    )
    return ConversationHandler.END


async def subscribe_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _reply(update, 'Подписка на что? Напишите "событие" или "будущие". /cancel для отмены.')
    return BotState.SUBSCRIBE_CHOICE


async def subscribe_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = (update.message.text or '').lower()
    await update.message.reply_text(f'Подписка оформлена: {choice} (заглушка).')
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _reply(update, 'Окей, отменил. /start')
    return ConversationHandler.END


async def networking_accept(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    match = await _get_current_match_async(context)
    if not match:
        await _reply(update, 'Нет активного предложения. /start', show_menu=True)
        return ConversationHandler.END
    await _mark_match_status_async(match, NetworkingMatchStatus.ACCEPTED)
    await _reply(update, f'Свяжитесь с {match.target_profile.contact or "контактом"}. Удачного общения!', show_menu=True)
    context.user_data.pop('current_match_id', None)
    return ConversationHandler.END


async def networking_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    match = await _get_current_match_async(context)
    if not match:
        await _reply(update, 'Нет активного предложения. /start', show_menu=True)
        return ConversationHandler.END
    await _mark_match_status_async(match, NetworkingMatchStatus.SKIPPED)

    source_profile = match.source_profile
    next_profile = await _get_next_match_async(source_profile)
    if not next_profile:
        await _send_search_menu(
            update,
            'Пока анкеты закончились. Как появятся новые — напомню. Можете вернуться в меню или попробовать позже.',
        )
        context.user_data.pop('current_match_id', None)
        return ConversationHandler.END

    new_match = await _create_match_async(source_profile=source_profile, target_profile=next_profile)
    context.user_data['current_match_id'] = new_match.id
    await _send_match_card(update, next_profile, new_match)
    return BotState.NETWORKING_MATCH


async def networking_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _send_search_menu(update, 'Хорошо, остановил подбор. Вернуться в меню или попробовать ещё позже?')
    context.user_data.pop('current_match_id', None)
    return ConversationHandler.END


async def _reply(update: Update, text: str, show_menu: bool = False) -> None:
    """message или callback"""
    markup = _menu_keyboard() if show_menu else None
    if update.message:
        await update.message.reply_text(text, reply_markup=markup)
    elif update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(text, reply_markup=markup)
        except Exception:
            await update.callback_query.message.reply_text(text, reply_markup=markup)


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
    return await sync_to_async(_ensure_participant, thread_sensitive=True)(update)


async def _get_active_event_async() -> Event | None:
    return await sync_to_async(lambda: Event.objects.filter(is_active=True).order_by('-start_at').first(), thread_sensitive=True)()


async def _get_profile_async(participant: Participant, event: Event) -> NetworkingProfile | None:
    return await sync_to_async(
        lambda: NetworkingProfile.objects.filter(participant=participant, event=event, is_active=True).first(),
        thread_sensitive=True,
    )()


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
        [InlineKeyboardButton('Дальше', callback_data='match_skip')],
        [InlineKeyboardButton('Стоп', callback_data='match_stop')],
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
