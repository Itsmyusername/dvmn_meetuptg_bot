from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from asgiref.sync import sync_to_async

from meetbot.services.utils_bot import (
    _ensure_participant_async,
    _reply,
    _get_active_event_async,
    _get_current_talk_async,
)

from meetbot.bot.constants import CB_Q_ACCEPT_PREFIX, CB_Q_REJECT_PREFIX
from meetbot.models import QuestionStatus, Question


async def show_questions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            'Нет активного события.',
            show_menu=True,
            participant=participant,
        )
        return

    talk = await _get_current_talk_async(event)
    if not talk:
        await _reply(
            update,
            'Нет активного доклада.',
            show_menu=True,
            participant=participant,
        )
        return

    questions = await sync_to_async(
        lambda: list(
            talk.questions
            .select_related('author')
            .filter(status=QuestionStatus.PENDING)
            .order_by('asked_at')
        ),
        thread_sensitive=True,
    )()

    if not questions:
        await _reply(
            update,
            'Нет вопросов в очереди для ответа.',
            show_menu=True,
            participant=participant,
        )
        return

    for q in questions:
        author = q.author

        if author and author.tg_username:
            name = f'@{author.tg_username}'
        else:
            parts = []
            if author and author.first_name:
                parts.append(author.first_name)
            if author and author.last_name:
                parts.append(author.last_name)
            name = ' '.join(parts).strip() or 'Аноним'

        author_id = author.tg_id if author else None

        if author_id:
            clickable_name = f'[{name}](tg://user?id={author_id})'
        else:
            clickable_name = name

        text = (
            f'❓ *{q.text}*\n'
            f'От: {clickable_name}'
        )

        buttons = [
            [
                InlineKeyboardButton(
                    'Отметить как отвеченный',
                    callback_data=f'{CB_Q_ACCEPT_PREFIX}{q.id}',
                ),
                InlineKeyboardButton(
                    'Отклонить',
                    callback_data=f'{CB_Q_REJECT_PREFIX}{q.id}',
                ),
            ]
        ]

        await update.effective_chat.send_message(
            text=text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(buttons),
        )


async def question_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q_id = int(update.callback_query.data.replace(CB_Q_ACCEPT_PREFIX, ''))
    question = await sync_to_async(lambda: Question.objects.get(id=q_id))()

    await sync_to_async(
        lambda: Question.objects.filter(id=q_id).update(status=QuestionStatus.ANSWERED),
        thread_sensitive=True,
    )()

    await update.callback_query.answer('Отмечено как отвеченный')
    await update.callback_query.edit_message_reply_markup(None)


async def question_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q_id = int(update.callback_query.data.replace(CB_Q_REJECT_PREFIX, ''))
    question = await sync_to_async(lambda: Question.objects.get(id=q_id))()

    await sync_to_async(
        lambda: Question.objects.filter(id=q_id).update(status=QuestionStatus.REJECTED),
        thread_sensitive=True,
    )()

    await update.callback_query.answer('Отклонён')
    await update.callback_query.edit_message_reply_markup(None)
