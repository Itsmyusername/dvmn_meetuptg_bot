import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from asgiref.sync import sync_to_async
from meetbot.models import (
    Event,
    NetworkingMatch,
    NetworkingMatchStatus,
    NetworkingProfile,
    Participant,
    QuestionStatus,
    Talk,
    TalkStatus,
    DonationStatus,
    Donation,
    Subscription,
    SubscriptionType,
)
from meetbot.services.networking import (
    count_profiles_for_event,
    create_match,
    get_next_match,
    get_or_create_profile,
    get_waiting_profile,
    mark_match_status,
)
from meetbot.services.donations import create_donation, create_yookassa_payment, refresh_payment_status
from meetbot.services.talks import create_question, finish_talk, get_current_talk, get_next_talk, start_talk

from .constants import (
    CB_MAIN_MENU,
    CB_DONATE,
    CB_NETWORKING,
    CB_NETWORK_START,
    CB_NETWORK_SEARCH,
    CB_PROGRAM,
    CB_QUESTION,
    CB_SPEAKER_MENU,
    CB_ORGANIZER_MENU,
    CB_DONATE_PAY_PREFIX,
    CB_DONATE_STATUS_PREFIX,
    CB_TALK_FINISH_PREFIX,
    CB_TALK_START_PREFIX,
    CB_TALK_SELECT_PREFIX,
    CB_MATCH_ACCEPT,
    CB_MATCH_SKIP,
    CB_MATCH_STOP,
    CB_SUBSCRIBE,
    CB_SUBSCRIBE_EVENT,
    CB_SUBSCRIBE_FUTURE,
    CMD_ASK,
    CMD_CANCEL,
    CMD_HEALTH,
    CMD_NETWORKING,
    CMD_PROGRAM,
    CMD_START,
    BotState,
)

logger = logging.getLogger(__name__)


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
        '• Смотрите программу и что идёт дальше\n'
        '• Познакомьтесь с участниками в формате “анкет и мэтчей”\n'
        '• Спикер может завершить доклад кнопкой, чтобы вопросы ушли следующему\n'
        f'Вы зашли как: {role_hint}'
    )

    await _reply(update, text, show_menu=True, participant=participant)


async def program(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    event = await _get_active_event_async()
    if not event:
        await _reply(
            update,
            'Сейчас нет активного события. Следите за обновлениями.',
            show_menu=True,
            participant=participant,
        )
        return

    current_talk = await _get_current_talk_async(event)
    next_talk = await _get_next_talk_async(event)

    parts = []
    if current_talk:
        parts.append(
            (
                "Сейчас идёт:\n"
                f"{current_talk.title}\n"
                f"Докладчик: {current_talk.speaker or 'уточняется'}\n"
                f"Время: {current_talk.start_at:%H:%M}–{current_talk.end_at:%H:%M}"
            )
        )
    else:
        parts.append('Сейчас доклад не идёт.')

    if next_talk:
        parts.append(
            (
                "Дальше по программе:\n"
                f"{next_talk.title}\n"
                f"Докладчик: {next_talk.speaker or 'уточняется'}\n"
                f"Начало: {next_talk.start_at:%H:%M}"
            )
        )

    parts.append('Нужен другой спикер? Организатор или докладчик могут отметить текущий доклад вручную.')
    await _reply(update, '\n\n'.join(parts), show_menu=True, participant=participant)


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ask_start(update, context)


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
        '4) Если вы первый, бот напомнит, когда появятся новые анкеты\n'
        'Контакт видит только человек, которого вы выбрали.'
    )

    buttons = [
        [
            InlineKeyboardButton('Заполнить анкету', callback_data=CB_NETWORK_START),
            InlineKeyboardButton('Отмена', callback_data=CB_MAIN_MENU),
        ]
    ]
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
    participant = await _ensure_participant_async(update)
    event = await _get_active_event_async()
    if not event:
        await _reply(update, 'Нет активного события. Донаты включим, когда стартует митап.', show_menu=True, participant=participant)
        return

    buttons = [
        [
            InlineKeyboardButton('100 ₽', callback_data=f'{CB_DONATE_PAY_PREFIX}100'),
            InlineKeyboardButton('300 ₽', callback_data=f'{CB_DONATE_PAY_PREFIX}300'),
            InlineKeyboardButton('500 ₽', callback_data=f'{CB_DONATE_PAY_PREFIX}500'),
        ],
        [InlineKeyboardButton('Отмена', callback_data=CB_MAIN_MENU)],
    ]
    text = (
        'Поддержите митап донатом. Выберите сумму или введите свою командой /donate (число).\n'
        'Оплата через ЮKassa, ссылку отправлю в ответ.'
    )
    await _send_with_markup(update, text, InlineKeyboardMarkup(buttons))


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    event = await _get_active_event_async()
    if not participant:
        await _reply(update, 'Не удалось определить пользователя.', show_menu=True)
        return

    event_sub_active = False
    if event:
        event_sub_active = await _has_subscription_async(participant, event, SubscriptionType.EVENT)
    future_sub_active = await _has_subscription_async(participant, None, SubscriptionType.FUTURE)

    buttons = []
    if event:
        buttons.append(
            [
                InlineKeyboardButton(
                    f"{'✅' if event_sub_active else '➕'} Обновления текущего события",
                    callback_data=CB_SUBSCRIBE_EVENT,
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(
                f"{'✅' if future_sub_active else '➕'} Уведомлять о следующих митапах",
                callback_data=CB_SUBSCRIBE_FUTURE,
            )
        ]
    )
    buttons.append([InlineKeyboardButton('Главное меню', callback_data=CB_MAIN_MENU)])

    text_parts = ['Подписки:']
    if event:
        text_parts.append(f"Текущее событие: {event.name}")
    text_parts.append('Нажмите на пункт, чтобы включить/выключить подписку.')
    await _send_with_markup(update, '\n'.join(text_parts), InlineKeyboardMarkup(buttons))


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
        CB_MAIN_MENU: start,
        CB_NETWORKING: networking,
        CB_SPEAKER_MENU: speaker_menu,
        CB_ORGANIZER_MENU: organizer_menu,
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
    participant = await _ensure_participant_async(update)
    event = await _get_active_event_async()
    if not event:
        await _reply(update, 'Сейчас нет активного события. Загляните позже.', show_menu=True, participant=participant)
        return ConversationHandler.END

    # если выбрали доклад из списка
    if update.callback_query and update.callback_query.data.startswith(CB_TALK_SELECT_PREFIX):
        try:
            talk_id = int(update.callback_query.data.replace(CB_TALK_SELECT_PREFIX, '', 1))
        except ValueError:
            talk_id = None
        talk = await _get_talk_by_id_async(talk_id) if talk_id else None
        if not talk:
            await _reply(update, 'Доклад не найден. Попробуйте выбрать снова.', show_menu=True, participant=participant)
            return ConversationHandler.END
        context.user_data['current_talk_id'] = talk.id
        speaker = talk.speaker or None
        speaker_text = f"Докладчик: {speaker}" if speaker else 'Докладчик: уточняется'
        await _reply(
            update,
            (
                f"Доклад:\n{talk.title}\n{speaker_text}\n\n"
                "Напишите ваш вопрос, я передам спикеру."
            ),
            show_menu=False,
            participant=participant,
        )
        return BotState.ASK_TEXT

    talk = await _get_current_talk_async(event)
    if talk:
        context.user_data['current_talk_id'] = talk.id
        speaker = talk.speaker or None
        speaker_text = f"Докладчик: {speaker}" if speaker else 'Докладчик: уточняется'
        await _send_with_markup(
            update,
            (
                f"Сейчас идёт доклад:\n{talk.title}\n{speaker_text}\n\n"
                "Напишите ваш вопрос, я передам спикеру."
            ),
            InlineKeyboardMarkup([[InlineKeyboardButton('Отмена', callback_data=CB_MAIN_MENU)]]),
        )
        return BotState.ASK_TEXT

    talks = await _list_event_talks_async(event)
    if not talks:
        await _reply(
            update,
            'Программа не заполнена. Спросите организаторов или зайдите позже.',
            show_menu=True,
            participant=participant,
        )
        return ConversationHandler.END

    buttons = [
        [
            InlineKeyboardButton(
                f"{t.start_at:%H:%M} {t.title[:40]}",
                callback_data=f"{CB_TALK_SELECT_PREFIX}{t.id}",
            )
        ]
        for t in talks[:6]
    ]
    buttons.append([InlineKeyboardButton('Главное меню', callback_data=CB_MAIN_MENU)])
    markup = InlineKeyboardMarkup(buttons)
    text = 'Выберите доклад, которому хотите задать вопрос.'
    if update.message:
        await update.message.reply_text(text, reply_markup=markup)
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    return ConversationHandler.END


async def ask_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    question_text = update.message.text if update.message else ''
    participant = await _ensure_participant_async(update)
    event = await _get_active_event_async()
    talk = None

    talk_id = context.user_data.pop('current_talk_id', None)
    if talk_id:
        talk = await _get_talk_by_id_async(talk_id)
    if not talk and event:
        talk = await _get_current_talk_async(event)

    if not (event and talk):
        await _reply(update, 'Нет активного доклада. Попробуйте позже.', show_menu=True, participant=participant)
        return ConversationHandler.END

    question = await _create_question_async(talk=talk, author=participant, text=question_text)
    delivered = await _notify_speaker_async(question, context.application.bot)
    if delivered:
        await _set_question_status_async(question, QuestionStatus.SENT_TO_SPEAKER)
    await update.message.reply_text('Спасибо! Вопрос передал спикеру. /start')
    return ConversationHandler.END


async def networking_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    
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
    participant = await _ensure_participant_async(update)
    event = await _get_active_event_async()
    if not event:
        await _reply(update, 'Нет активного события. Донаты включим позже.', show_menu=True, participant=participant)
        return ConversationHandler.END
    await _reply(update, 'Введите сумму доната в рублях. /cancel для отмены.', show_menu=False)
    return BotState.DONATE_AMOUNT


async def donate_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    amount_text = (update.message.text or '').strip()
    participant = await _ensure_participant_async(update)
    event = await _get_active_event_async()
    if not event:
        await _reply(update, 'Нет активного события. Донаты включим позже.', show_menu=True, participant=participant)
        return ConversationHandler.END

    try:
        amount = float(amount_text.replace(',', '.'))
    except ValueError:
        await update.message.reply_text('Нужна сумма числом, например 200 или 350. Попробуйте ещё раз.')
        return BotState.DONATE_AMOUNT

    if amount < 50:
        await update.message.reply_text('Минимальная сумма 50 ₽. Введите больше.')
        return BotState.DONATE_AMOUNT

    donation = await _create_donation_async(
        participant=participant,
        event=event,
        amount=amount,
        description=f'Поддержка митапа {event.name}',
    )
    donation = await _create_yookassa_payment_async(donation)
    if not donation.confirmation_url:
        await update.message.reply_text('Не смогли создать оплату. Попробуйте позже.')
        return ConversationHandler.END

    await update.message.reply_text(
        f'Ссылка на оплату {donation.amount} ₽: {donation.confirmation_url}\n'
        'После оплаты нажмите “Проверить статус”. Спасибо за поддержку!',
        reply_markup=_donation_markup(donation),
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


async def subscribe_toggle_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    event = await _get_active_event_async()
    if not (participant and event):
        await _reply(update, 'Нет активного события.', show_menu=True, participant=participant)
        return
    toggled = await _toggle_subscription_async(participant, event, SubscriptionType.EVENT)
    msg = 'Подписка на обновления текущего события включена.' if toggled else 'Подписка на обновления текущего события выключена.'
    await _reply(update, msg, show_menu=True, participant=participant)


async def subscribe_toggle_future(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    if not participant:
        await _reply(update, 'Не удалось определить пользователя.', show_menu=True)
        return
    toggled = await _toggle_subscription_async(participant, None, SubscriptionType.FUTURE)
    msg = 'Подписка на будущие митапы включена.' if toggled else 'Подписка на будущие митапы выключена.'
    await _reply(update, msg, show_menu=True, participant=participant)


async def donate_pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    event = await _get_active_event_async()
    if not event:
        await _reply(update, 'Нет активного события. Донаты включим позже.', show_menu=True, participant=participant)
        return
    amount = _parse_amount_from_callback(update, CB_DONATE_PAY_PREFIX)
    if not amount:
        await _reply(update, 'Не удалось понять сумму. Попробуйте снова.', show_menu=True, participant=participant)
        return
    donation = await _create_donation_async(
        participant=participant,
        event=event,
        amount=amount,
        description=f'Поддержка митапа {event.name}',
    )
    donation = await _create_yookassa_payment_async(donation)
    if not donation.confirmation_url:
        await _reply(update, 'Не смогли создать оплату. Попробуйте позже.', show_menu=True, participant=participant)
        return
    text = (
        f'Ссылка на оплату {donation.amount} ₽: {donation.confirmation_url}\n'
        'После оплаты нажмите “Проверить статус”. Спасибо!'
    )
    await _send_with_markup(update, text, _donation_markup(donation))


async def donate_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    donation_id = _parse_id_from_callback(update, CB_DONATE_STATUS_PREFIX)
    participant = await _ensure_participant_async(update)
    if not donation_id:
        await _reply(update, 'Платёж не найден.', show_menu=True, participant=participant)
        return
    donation = await _get_donation_by_id_async(donation_id)
    if not donation:
        await _reply(update, 'Платёж не найден.', show_menu=True, participant=participant)
        return
    donation = await _refresh_payment_async(donation)
    status_text = {
        DonationStatus.PENDING: 'Ожидает оплаты',
        DonationStatus.WAITING_FOR_CAPTURE: 'Ожидает подтверждения',
        DonationStatus.SUCCEEDED: 'Оплата прошла, спасибо!',
        DonationStatus.FAILED: 'Неуспешно',
        DonationStatus.CANCELED: 'Отменено',
    }.get(donation.status, donation.status)
    await _send_with_markup(
        update,
        f'Статус платежа: {status_text}\nСумма: {donation.amount} ₽',
        _donation_markup(donation),
    )


async def speaker_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    if not participant or not participant.is_speaker:
        await _reply(update, 'Панель докладчика доступна только назначенным спикерам.', show_menu=True, participant=participant)
        return

    event = await _get_active_event_async()
    if not event:
        await _reply(update, 'Нет активного мероприятия. Как только начнётся — напомню.', show_menu=True, participant=participant)
        return

    talks = await _list_speaker_talks_async(participant, event)
    if not talks:
        await _reply(
            update,
            'В программе нет докладов, где вы отмечены спикером. Проверьте с организатором.',
            show_menu=True,
            participant=participant,
        )
        return

    current_talk = await _get_current_talk_async(event)
    lines = ['Ваши доклады на событие:']
    buttons = []
    for talk in talks:
        pending = await _count_pending_questions_async(talk)
        status_emoji = {
            TalkStatus.IN_PROGRESS: '▶️',
            TalkStatus.DONE: '✅',
            TalkStatus.CANCELLED: '🚫',
        }.get(talk.status, '⏳')
        line = (
            f"{status_emoji} {talk.start_at:%H:%M}-{talk.end_at:%H:%M} {talk.title} "
            f"(вопросов в очереди: {pending})"
        )
        lines.append(line)
        if talk.status not in (TalkStatus.DONE, TalkStatus.CANCELLED):
            if current_talk and current_talk.id == talk.id:
                buttons.append(
                    [
                        InlineKeyboardButton('✅ Завершить доклад', callback_data=f'{CB_TALK_FINISH_PREFIX}{talk.id}'),
                    ]
                )
            else:
                buttons.append(
                    [InlineKeyboardButton('▶️ Сделать текущим', callback_data=f'{CB_TALK_START_PREFIX}{talk.id}')]
                )
    buttons.append([InlineKeyboardButton('Главное меню', callback_data=CB_MAIN_MENU)])
    buttons.append([InlineKeyboardButton('Программа', callback_data=CB_PROGRAM)])
    buttons.append([InlineKeyboardButton('Задать вопрос', callback_data=CB_QUESTION)])

    await _send_with_markup(
        update,
        '\n'.join(lines)
        + '\n\nНажмите “Сделать текущим” перед выходом на сцену и “Завершить доклад”, когда закончили.',
        InlineKeyboardMarkup(buttons),
    )


async def organizer_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    if not participant or not participant.is_organizer:
        await _reply(update, 'Панель организатора доступна только организаторам.', show_menu=True, participant=participant)
        return

    event = await _get_active_event_async()
    if not event:
        await _reply(update, 'Нет активного мероприятия. Создайте и активируйте событие в админке.', show_menu=True, participant=participant)
        return

    talks = await _list_event_talks_async(event)
    current_talk = await _get_current_talk_async(event)
    header = f'Активное событие: {event.name}\n{event.start_at:%d.%m %H:%M}–{event.end_at:%H:%M}'
    if not talks:
        await _reply(
            update,
            header + '\nВ программе пока нет докладов. Добавьте их в админке.',
            show_menu=True,
            participant=participant,
        )
        return

    lines = [header, '', 'Список докладов:']
    buttons = []
    for talk in talks[:15]:
        pending = await _count_pending_questions_async(talk)
        marker = '▶️' if current_talk and talk.id == current_talk.id else '•'
        lines.append(
            f"{marker} {talk.start_at:%H:%M}-{talk.end_at:%H:%M} {talk.title} "
            f"({talk.speaker or 'спикер уточняется'}) — вопросов: {pending}"
        )
        if talk.status not in (TalkStatus.DONE, TalkStatus.CANCELLED):
            if current_talk and talk.id == current_talk.id:
                buttons.append(
                    [
                        InlineKeyboardButton(
                            f'Завершить: {talk.title[:18]}', callback_data=f'{CB_TALK_FINISH_PREFIX}{talk.id}'
                        )
                    ]
                )
            else:
                buttons.append(
                    [
                        InlineKeyboardButton(
                            f'Сделать текущим: {talk.title[:18]}', callback_data=f'{CB_TALK_START_PREFIX}{talk.id}'
                        )
                    ]
                )
    buttons.append([InlineKeyboardButton('Главное меню', callback_data=CB_MAIN_MENU)])
    await _send_with_markup(
        update,
        '\n'.join(lines)
        + '\n\nОтмечайте текущий доклад вручную — так вопросы уйдут правильному спикеру даже при сдвигах по времени.',
        InlineKeyboardMarkup(buttons),
    )


async def talk_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    talk_id = _parse_id_from_callback(update, CB_TALK_START_PREFIX)
    talk = await _get_talk_by_id_async(talk_id) if talk_id else None
    if not talk:
        await _reply(update, 'Доклад не найден.', show_menu=True, participant=participant)
        return

    if not participant or not (participant.is_organizer or (participant.is_speaker and talk.speaker_id == participant.id)):
        await _reply(update, 'Только организатор или назначенный спикер могут менять статус доклада.', show_menu=True, participant=participant)
        return

    await _start_talk_async(talk)
    if update.callback_query:
        await update.callback_query.answer('Доклад сделан текущим.')
    if participant.is_organizer:
        await organizer_menu(update, context)
    elif participant.is_speaker:
        await speaker_menu(update, context)
    else:
        await _reply(
            update,
            f'Отметил доклад "{talk.title}" как текущий. Вопросы пойдут этому спикеру.',
            show_menu=True,
            participant=participant,
        )


async def talk_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    talk_id = _parse_id_from_callback(update, CB_TALK_FINISH_PREFIX)
    talk = await _get_talk_by_id_async(talk_id) if talk_id else None
    if not talk:
        await _reply(update, 'Доклад не найден.', show_menu=True, participant=participant)
        return

    if not participant or not (participant.is_organizer or (participant.is_speaker and talk.speaker_id == participant.id)):
        await _reply(update, 'Только организатор или назначенный спикер могут завершать доклад.', show_menu=True, participant=participant)
        return

    await _finish_talk_async(talk)
    if update.callback_query:
        await update.callback_query.answer('Доклад завершён.')
    if participant.is_organizer:
        await organizer_menu(update, context)
    elif participant.is_speaker:
        await speaker_menu(update, context)
    else:
        await _reply(
            update,
            f'Доклад "{talk.title}" завершён. Следующие вопросы уйдут следующему спикеру.',
            show_menu=True,
            participant=participant,
        )


async def announce_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    participant = await _ensure_participant_async(update)
    if not participant or not participant.is_organizer:
        await _reply(update, 'Рассылку может запускать только организатор.', show_menu=True, participant=participant)
        return ConversationHandler.END

    event = await _get_active_event_async()
    if not event:
        await _reply(update, 'Нет активного события для рассылки.', show_menu=True, participant=participant)
        return ConversationHandler.END

    context.user_data['announce_event_id'] = event.id
    await _reply(
        update,
        'Пришлите текст объявления — отправлю всем, кто не отключил уведомления. /cancel для отмены.',
        show_menu=False,
    )
    return BotState.ANNOUNCE_TEXT


async def announce_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text if update.message else ''
    event = await _get_active_event_async()
    if not event:
        await update.message.reply_text('Нет активного события — рассылку не отправил.')
        return ConversationHandler.END

    recipients = await _list_notification_participants_async()
    sent = 0
    for participant in recipients:
        try:
            await context.application.bot.send_message(
                chat_id=participant.tg_id,
                text=f'Новость по "{event.name}":\n\n{text}',
            )
            sent += 1
        except Exception:
            continue
    await update.message.reply_text(f'Рассылка отправлена {sent} участникам.')
    return ConversationHandler.END


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


async def _attach_speaker_flag_async(participant: Participant | None, event: Event | None) -> Participant | None:
    """Помечает участника как спикера для меню, если он привязан к докладу активного события."""
    if not (participant and event):
        return participant
    has_talk = await _has_speaker_talk_async(participant, event)
    if has_talk:
        participant._has_speaker_talk = True  # noqa: SLF001 
    return participant


async def _get_active_event_async() -> Event | None:
    return await sync_to_async(lambda: Event.objects.filter(is_active=True).order_by('-start_at').first(), thread_sensitive=True)()


async def _get_profile_async(participant: Participant, event: Event) -> NetworkingProfile | None:
    return await sync_to_async(
        lambda: NetworkingProfile.objects.filter(participant=participant, event=event, is_active=True).first(),
        thread_sensitive=True,
    )()


async def _get_current_talk_async(event: Event) -> Talk | None:
    return await sync_to_async(get_current_talk, thread_sensitive=True)(event)


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


async def _get_talk_by_id_async(talk_id: int) -> Talk | None:
    return await sync_to_async(lambda: Talk.objects.select_related('speaker').filter(id=talk_id).first(), thread_sensitive=True)()


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


async def _list_event_talks_async(event: Event):
    return await sync_to_async(lambda: list(event.talks.select_related('speaker').order_by('start_at')), thread_sensitive=True)()


async def _set_question_status_async(question, status: str) -> None:
    def _set_status(q, s):
        q.status = s
        q.save(update_fields=['status'])

    await sync_to_async(_set_status, thread_sensitive=True)(question, status)


async def _count_pending_questions_async(talk: Talk) -> int:
    return await sync_to_async(
        lambda: talk.questions.filter(status=QuestionStatus.PENDING).count(),
        thread_sensitive=True,
    )()


async def _list_speaker_talks_async(participant: Participant, event: Event):
    return await sync_to_async(
        lambda: list(
            event.talks.select_related('speaker')
            .filter(speaker=participant)
            .order_by('start_at')
        ),
        thread_sensitive=True,
    )()


async def _has_speaker_talk_async(participant: Participant, event: Event) -> bool:
    return await sync_to_async(
        lambda: event.talks.filter(speaker=participant).exists(),
        thread_sensitive=True,
    )()


async def _start_talk_async(talk: Talk) -> Talk:
    return await sync_to_async(start_talk, thread_sensitive=True)(talk)


async def _finish_talk_async(talk: Talk) -> Talk:
    return await sync_to_async(finish_talk, thread_sensitive=True)(talk)


async def _list_notification_participants_async():
    return await sync_to_async(
        lambda: list(Participant.objects.filter(wants_notifications=True)),
        thread_sensitive=True,
    )()


def _parse_id_from_callback(update: Update, prefix: str) -> int | None:
    query = update.callback_query
    if not query or not query.data or not query.data.startswith(prefix):
        return None
    try:
        return int(query.data.replace(prefix, '', 1))
    except ValueError:
        return None


def _parse_amount_from_callback(update: Update, prefix: str) -> float | None:
    value = _parse_id_from_callback(update, prefix)
    if value is None:
        return None
    return float(value)


async def _send_with_markup(update: Update, text: str, reply_markup) -> None:
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        except Exception:
            await update.callback_query.message.reply_text(text, reply_markup=reply_markup)


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
