import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from meetbot.models import DonationStatus, QuestionStatus, SubscriptionType
from meetbot.services.utils_bot import (
    _create_donation_async,
    _create_question_async,
    _create_yookassa_payment_async,
    _donation_markup,
    _donations_summary_async,
    _ensure_participant_async,
    _get_active_event_async,
    _get_donation_by_id_async,
    _get_current_talk_async,
    _get_subscribed_event_async,
    _get_talk_by_id_async,
    _has_subscription_async,
    _list_event_talks_async,
    _list_subscribers_async,
    _menu_keyboard,
    _parse_amount_from_callback,
    _parse_id_from_callback,
    _refresh_payment_async,
    _reply,
    _send_with_markup,
    _toggle_subscription_async,
)
from .constants import (
    BotState,
    CB_QUESTION,
    CB_DONATE,
    CB_DONATE_PAY_PREFIX,
    CB_DONATE_STATUS_PREFIX,
    CB_DONATIONS,
    CB_MAIN_MENU,
    CB_NETWORKING,
    CB_ORGANIZER_MENU,
    CB_PROGRAM,
    CB_PROGRAM_NOTIFY,
    CB_SPEAKER_APPLY,
    CB_SPEAKER_MENU,
    CB_SUBSCRIBE,
    CB_SUBSCRIBE_EVENT,
    CB_SUBSCRIBE_FUTURE,
    CB_TALK_SELECT_PREFIX,
)
from .event_program import get_program_text
from .networking_handlers import networking
from .organizer_panel import organizer_menu
from .speaker_handlers import speaker_apply_start, speaker_menu

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Стартовая команда."""
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
    text = await get_program_text()
    await _reply(update, text, show_menu=True, participant=participant)


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ask_start(update, context)


async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    event = await _get_active_event_async()
    if not event:
        await _reply(
            update,
            'Нет активного события. Донаты включим, когда стартует митап.',
            show_menu=True,
            participant=participant,
        )
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
        event_sub_active = await _has_subscription_async(
            participant, event, SubscriptionType.EVENT
        )
    future_sub_active = await _has_subscription_async(
        participant, None, SubscriptionType.FUTURE
    )

    buttons = []
    if event:
        buttons.append(
            [
                InlineKeyboardButton(
                    f"{'✅' if event_sub_active else '➕'} "
                    "Подписаться на уведомления текущего мероприятия",
                    callback_data=CB_SUBSCRIBE_EVENT,
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(
                f"{'✅' if future_sub_active else '➕'} "
                'Уведомлять о следующих митапах',
                callback_data=CB_SUBSCRIBE_FUTURE,
            )
        ]
    )
    buttons.append([InlineKeyboardButton('Главное меню', callback_data=CB_MAIN_MENU)])

    text_parts = ['Подписки:']
    if event:
        text_parts.append(f'Текущее мероприятие: {event.name}')
    text_parts.append('Нажмите на пункт, чтобы включить/выключить подписку.')
    await _send_with_markup(update, '\n'.join(text_parts), InlineKeyboardMarkup(buttons))


async def donations_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    if not participant or not participant.is_organizer:
        await _reply(
            update,
            'Отчёт по донатам доступен только организаторам.',
            show_menu=True,
            participant=participant,
        )
        return

    event = await _get_active_event_async()
    if not event:
        await _reply(update, 'Нет активного события.', show_menu=True, participant=participant)
        return

    summary = await _donations_summary_async(event)
    lines = [f'Донаты по событию: {event.name}']
    lines.append(f"Всего: {summary['total']} ₽, платежей: {summary['count']}")

    if summary['items']:
        lines.append('Последние платежи:')
        for donation in summary['items']:
            lines.append(
                f"{donation['amount']} ₽ — {donation['status']} ({donation['who']})"
            )
    else:
        lines.append('Пока нет донатов.')

    await _reply(update, '\n'.join(lines), show_menu=True, participant=participant)


async def program_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    if not participant or not participant.is_organizer:
        await _reply(
            update,
            'Оповестить о программе может только организатор.',
            show_menu=True,
            participant=participant,
        )
        return

    event = await _get_active_event_async()
    subscribers = await _list_subscribers_async(event) if event else []
    chosen_event = event

    if not subscribers:
        chosen_event = await _get_subscribed_event_async()
        if chosen_event:
            subscribers = await _list_subscribers_async(chosen_event)

    if not chosen_event:
        await _reply(update, 'Нет события для рассылки.', show_menu=True, participant=participant)
        return

    talks = await _list_event_talks_async(chosen_event)
    if not talks:
        await _reply(
            update,
            'В программе нет докладов, оповещать нечего.',
            show_menu=True,
            participant=participant,
        )
        return

    text_lines = [f'Программа события: {chosen_event.name}']
    for talk in talks:
        text_lines.append(
            f'{talk.start_at:%H:%M}-{talk.end_at:%H:%M} {talk.title} — '
            f"{talk.speaker or 'спикер уточняется'}"
        )
    message = '\n'.join(text_lines)

    if not subscribers:
        await _reply(update, 'Некому отправить — нет подписчиков.', show_menu=True, participant=participant)
        return

    sent = 0
    failed = 0
    for sub in subscribers:
        try:
            await context.application.bot.send_message(chat_id=sub.tg_id, text=message)
            sent += 1
        except Exception:
            failed += 1

    info = f'Рассылка программы ({chosen_event.name}) отправлена {sent} пользователям.'
    if failed:
        info += f' Ошибок доставки: {failed}.'
    await _reply(update, info, show_menu=True, participant=participant)


async def health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, 'ok', show_menu=False)


async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ответы на кнопки главного меню."""
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
        CB_DONATIONS: donations_report,
        CB_SPEAKER_APPLY: speaker_apply_start,
        CB_PROGRAM_NOTIFY: program_notify,
        'program_notify': program_notify,  # для старых сообщений
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
        await _reply(
            update,
            'Сейчас нет активного события. Загляните позже.',
            show_menu=True,
            participant=participant,
        )
        return ConversationHandler.END

    if update.callback_query and update.callback_query.data.startswith(CB_TALK_SELECT_PREFIX):
        try:
            talk_id = int(update.callback_query.data.replace(CB_TALK_SELECT_PREFIX, '', 1))
        except ValueError:
            talk_id = None

        talk = await _get_talk_by_id_async(talk_id) if talk_id else None
        if not talk:
            await _reply(
                update,
                'Доклад не найден. Попробуйте выбрать снова.',
                show_menu=True,
                participant=participant,
            )
            return ConversationHandler.END

        context.user_data['current_talk_id'] = talk.id
        speaker_text = f'Докладчик: {talk.speaker}' if talk.speaker else 'Докладчик: уточняется'
        await _reply(
            update,
            f'Доклад:\n{talk.title}\n{speaker_text}\n\n'
            'Напишите ваш вопрос, я передам спикеру.',
            show_menu=False,
            participant=participant,
        )
        return BotState.ASK_TEXT

    talk = await _get_current_talk_async(event)
    if talk:
        context.user_data['current_talk_id'] = talk.id
        speaker_text = f'Докладчик: {talk.speaker}' if talk.speaker else 'Докладчик: уточняется'
        await _send_with_markup(
            update,
            f'Сейчас идёт доклад:\n{talk.title}\n{speaker_text}\n\n'
            'Напишите ваш вопрос, я передам спикеру.',
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
                f'{t.start_at:%H:%M} {t.title[:40]}',
                callback_data=f'{CB_TALK_SELECT_PREFIX}{t.id}',
            )
        ]
        for t in talks[:6]
    ]
    buttons.append([InlineKeyboardButton('Главное меню', callback_data=CB_MAIN_MENU)])

    text = 'Выберите доклад, которому хотите задать вопрос.'
    markup = InlineKeyboardMarkup(buttons)

    if update.message:
        await update.message.reply_text(text, reply_markup=markup)
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=markup)

    return ConversationHandler.END


async def ask_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message:
        return ConversationHandler.END

    question_text = update.message.text or ''
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

    await _create_question_async(talk=talk, author=participant, text=question_text)

    buttons = [
        [InlineKeyboardButton('Задать ещё вопрос', callback_data=CB_QUESTION)],
        [InlineKeyboardButton('Главное меню', callback_data=CB_MAIN_MENU)],
    ]
    await update.message.reply_text('Спасибо! Вопрос передал спикеру.', reply_markup=InlineKeyboardMarkup(buttons))
    return ConversationHandler.END


async def donate_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    participant = await _ensure_participant_async(update)
    event = await _get_active_event_async()
    if not event:
        await _reply(update, 'Нет активного события. Донаты включим позже.', show_menu=True, participant=participant)
        return ConversationHandler.END

    await _reply(update, 'Введите сумму доната в рублях. /cancel для отмены.', show_menu=False)
    return BotState.DONATE_AMOUNT


async def donate_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message:
        return ConversationHandler.END

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
    await _reply(
        update,
        'Подписка на что? Напишите "событие" или "будущие". /cancel для отмены.',
    )
    return BotState.SUBSCRIBE_CHOICE


async def subscribe_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message:
        return ConversationHandler.END

    choice = (update.message.text or '').lower()
    await update.message.reply_text(f'Подписка оформлена: {choice} (заглушка).')
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _reply(update, 'Окей, отменил. /start')
    return ConversationHandler.END


async def subscribe_toggle_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    event = await _get_active_event_async()
    if not (participant and event):
        await _reply(update, 'Нет активного события.', show_menu=True, participant=participant)
        return

    toggled = await _toggle_subscription_async(participant, event, SubscriptionType.EVENT)
    msg = (
        'Подписка на обновления текущего события включена.'
        if toggled
        else 'Подписка на обновления текущего события выключена.'
    )
    await _reply(update, msg, show_menu=True, participant=participant)


async def subscribe_toggle_future(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    if not participant:
        await _reply(update, 'Не удалось определить пользователя.', show_menu=True)
        return

    toggled = await _toggle_subscription_async(participant, None, SubscriptionType.FUTURE)
    msg = (
        'Подписка на будущие митапы включена.'
        if toggled
        else 'Подписка на будущие митапы выключена.'
    )
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
    if not update.message:
        return ConversationHandler.END

    text = update.message.text or ''
    event = await _get_active_event_async()

    recipients = await _list_subscribers_async(event) if event else []
    sent = 0
    for participant in recipients:
        try:
            await context.application.bot.send_message(
                chat_id=participant.tg_id,
                text=f"Новость{' по ' + event.name if event else ''}:\n\n{text}",
            )
            sent += 1
        except Exception:
            continue

    await update.message.reply_text(f'Рассылка отправлена {sent} участникам.')
    return ConversationHandler.END
