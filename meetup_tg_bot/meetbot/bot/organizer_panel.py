from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from meetbot.services.utils_bot import (
    _ensure_participant_async,
    _get_active_event_async,
    _get_current_talk_async,
    format_local,
    _reply,
    _send_with_markup,
    _list_event_talks_async,
    _question_stats_async,
)

from meetbot.bot.constants import (
    CB_TALK_FINISH_PREFIX,
    CB_TALK_START_PREFIX,
    CB_PROGRAM_NOTIFY,
    CB_DONATIONS,
    CB_MAIN_MENU,
    ORG_SHOW_QUESTIONS,
)

from meetbot.models import TalkStatus


async def organizer_menu(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
) -> None:
    participant = await _ensure_participant_async(update)

    if not participant or not (participant.is_organizer or participant.is_speaker):
        await _reply(
            update,
            'Доступ только для организаторов и спикеров.',
            show_menu=True,
            participant=participant,
        )
        return

    event = await _get_active_event_async()
    if not event:
        await _reply(
            update,
            'Нет активного мероприятия. Создайте и активируйте событие в админке.',
            show_menu=True,
            participant=participant,
        )
        return

    talks = await _list_event_talks_async(event)
    current_talk = await _get_current_talk_async(event)

    header = (
        f'Активное событие: {event.name}\n'
        f'{event.start_at:%d.%m.%y} '
        f'{format_local(event.start_at)}–{format_local(event.end_at)}'
    )

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
        marker = '▶️' if current_talk and talk.id == current_talk.id else '•'

        total, answered, rejected, pending = await _question_stats_async(talk)

        lines.append(
            f'{marker} {format_local(talk.start_at)}-{format_local(talk.end_at)} '
            f'{talk.title} ({talk.speaker or "спикер уточняется"})'
        )
        lines.append(
            f'   ❓Всего: {total} | Отвечено: {answered} | '
            f'Отклонено: {rejected} | В очереди: {pending}'
        )

        if talk.status not in (TalkStatus.DONE, TalkStatus.CANCELLED):
            label = (
                f'Завершить: {talk.title[:18]}'
                if current_talk and talk.id == current_talk.id
                else f'Сделать текущим: {talk.title[:18]}'
            )
            callback = (
                f'{CB_TALK_FINISH_PREFIX}{talk.id}'
                if current_talk and talk.id == current_talk.id
                else f'{CB_TALK_START_PREFIX}{talk.id}'
            )
            buttons.append([InlineKeyboardButton(label, callback_data=callback)])

    buttons.append([InlineKeyboardButton('❓ Вопросы к текущему', callback_data=ORG_SHOW_QUESTIONS)])
    buttons.append([InlineKeyboardButton('📣 Оповестить о программе', callback_data=CB_PROGRAM_NOTIFY)])
    buttons.append([InlineKeyboardButton('💸 Донаты', callback_data=CB_DONATIONS)])
    buttons.append([InlineKeyboardButton('Главное меню', callback_data=CB_MAIN_MENU)])

    await _send_with_markup(
        update,
        '\n'.join(lines)
        + '\n\nОтмечайте текущий доклад вручную — так вопросы уйдут правильному спикеру даже при сдвигах по времени.',
        InlineKeyboardMarkup(buttons),
    )
