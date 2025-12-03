import logging

from asgiref.sync import sync_to_async
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from meetbot.bot.constants import (
    CB_MAIN_MENU,
    CB_SPEAKER_MENU,
    CB_TALK_START_PREFIX,
    CB_TALK_FINISH_PREFIX,
    CB_PROGRAM,
    CB_QUESTION,
    ORG_SHOW_QUESTIONS,
    BotState,
)
from meetbot.models import (
    Event,
    Talk,
    TalkStatus,
    SpeakerApplication,
)
from meetbot.services.utils_bot import (
    _reply,
    _ensure_participant_async,
    _get_active_event_async,
    _get_current_talk_async,
    _list_speaker_talks_async,
    _start_talk_async,
    _finish_talk_async,
    _send_with_markup,
    format_local,
    _parse_id_from_callback,
    _get_talk_by_id_async,
    _question_stats_async,
    get_unpublished_events,
)

from .organizer_panel import organizer_menu

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------
# SPEAKER PANEL
# -----------------------------------------------------------------

async def speaker_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    event = await _get_active_event_async()

    if not participant or not participant.is_speaker:
        await _reply(
            update,
            'Панель докладчика доступна только назначенным спикерам.',
            show_menu=True,
            participant=participant,
        )
        return

    if not event:
        await _reply(
            update,
            'Нет активного мероприятия. Как только начнётся — напомню.',
            show_menu=True,
            participant=participant,
        )
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
        status_emoji = {
            TalkStatus.IN_PROGRESS: '▶️',
            TalkStatus.DONE: '✅',
            TalkStatus.CANCELLED: '🚫',
        }.get(talk.status, '⏳')

        total, answered, rejected, pending = await _question_stats_async(talk)

        lines.append(
            f'{status_emoji} {format_local(talk.start_at)}-{format_local(talk.end_at)} {talk.title}\n'
            f'❓Всего вопросов: {total} | Отвечено: {answered} | '
            f'Отклонено: {rejected} | В очереди: {pending}'
        )

        if talk.status not in (TalkStatus.DONE, TalkStatus.CANCELLED):
            if current_talk and current_talk.id == talk.id:
                buttons.append(
                    [
                        InlineKeyboardButton(
                            '✅ Завершить доклад',
                            callback_data=f'{CB_TALK_FINISH_PREFIX}{talk.id}',
                        )
                    ]
                )
            else:
                buttons.append(
                    [
                        InlineKeyboardButton(
                            '▶️ Сделать текущим',
                            callback_data=f'{CB_TALK_START_PREFIX}{talk.id}',
                        )
                    ]
                )

    buttons.append(
        [InlineKeyboardButton('❓ Вопросы к текущему докладу', callback_data=ORG_SHOW_QUESTIONS)]
    )
    buttons.append([InlineKeyboardButton('Программа', callback_data=CB_PROGRAM)])
    buttons.append([InlineKeyboardButton('Задать вопрос', callback_data=CB_QUESTION)])
    buttons.append([InlineKeyboardButton('Главное меню', callback_data=CB_MAIN_MENU)])

    await _send_with_markup(
        update,
        '\n'.join(lines)
        + '\n\nНажмите «Сделать текущим» перед выходом на сцену и «Завершить доклад», когда закончили.',
        InlineKeyboardMarkup(buttons),
    )


async def talk_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    participant = await _ensure_participant_async(update)
    talk_id = _parse_id_from_callback(update, CB_TALK_START_PREFIX)
    talk = await _get_talk_by_id_async(talk_id) if talk_id else None

    if not talk:
        await _reply(update, 'Доклад не найден.', show_menu=True, participant=participant)
        return

    if not participant or not (
        participant.is_organizer
        or (participant.is_speaker and talk.speaker_id == participant.id)
    ):
        await _reply(
            update,
            'Только организатор или назначенный спикер могут менять статус доклада.',
            show_menu=True,
            participant=participant,
        )
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
            f'Отметил доклад «{talk.title}» как текущий. Вопросы пойдут этому спикеру.',
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

    if not participant or not (
        participant.is_organizer
        or (participant.is_speaker and talk.speaker_id == participant.id)
    ):
        await _reply(
            update,
            'Только организатор или назначенный спикер могут завершать доклад.',
            show_menu=True,
            participant=participant,
        )
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
            f'Доклад «{talk.title}» завершён. Следующие вопросы уйдут следующему спикеру.',
            show_menu=True,
            participant=participant,
        )


# -----------------------------------------------------------------
# SPEAKER APPLY
# -----------------------------------------------------------------

async def speaker_apply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    participant = await _ensure_participant_async(update)
    events = await get_unpublished_events()

    if not events:
        await query.edit_message_text('Нет мероприятий, куда можно подать заявку спикера.')
        return

    if len(events) == 1:
        event = events[0]
        text = (
            f'🎤 *Мероприятие:* {event.name}\n'
            f'📅 {event.start_at.strftime("%d.%m.%Y")}\n\n'
            f'Хотите подать заявку как спикер?'
        )

        buttons = [
            [
                InlineKeyboardButton(
                    'Подать заявку',
                    callback_data=f'speaker_apply_event_{event.id}',
                )
            ],
            [InlineKeyboardButton('⬅ Назад', callback_data=CB_SPEAKER_MENU)],
        ]

        await query.edit_message_text(
            text=text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    text = 'Выберите мероприятие, куда хотите подать заявку как спикер:'

    buttons = [
        [
            InlineKeyboardButton(
                event.name,
                callback_data=f'speaker_apply_event_{event.id}',
            )
        ]
        for event in events
    ]

    buttons.append([InlineKeyboardButton('⬅ Назад', callback_data=CB_SPEAKER_MENU)])

    await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(buttons))


async def speaker_apply_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    event_id = int(query.data.replace('speaker_apply_event_', ''))
    context.user_data['speaker_event_id'] = event_id

    await query.edit_message_text('📝 Кратко опишите тему, с которой хотите выступить:')

    return BotState.SPEAKER_APPLY_TOPIC


async def speaker_apply_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if not text:
        await update.message.reply_text('Пожалуйста, опишите тему одним сообщением.')
        return BotState.SPEAKER_APPLY_TOPIC

    context.user_data['speaker_topic'] = text

    await update.message.reply_text('📞 Оставьте контакт для связи (телеграм, телефон или e-mail):')

    return BotState.SPEAKER_APPLY_CONTACT


async def speaker_apply_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.text.strip()

    if not contact:
        await update.message.reply_text('Пожалуйста, отправьте контакт одним сообщением.')
        return BotState.SPEAKER_APPLY_CONTACT

    topic = context.user_data.get('speaker_topic')
    event_id = context.user_data.get('speaker_event_id')

    if not topic or not event_id:
        await update.message.reply_text('Произошла ошибка. Попробуйте заново.')
        return ConversationHandler.END

    participant = await _ensure_participant_async(update)

    @sync_to_async
    def create_application():
        event = Event.objects.get(id=event_id)
        return SpeakerApplication.objects.create(
            event=event,
            participant=participant,
            topic=topic,
            contact=contact,
        )

    await create_application()

    context.user_data.pop('speaker_topic', None)
    context.user_data.pop('speaker_event_id', None)

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton('Главное меню', callback_data='menu_main')]]
    )

    await update.message.reply_text(
        '🎉 *Ваша заявка отправлена!* Мы свяжемся с вами после рассмотрения.',
        parse_mode='Markdown',
        reply_markup=keyboard,
    )

    return ConversationHandler.END
