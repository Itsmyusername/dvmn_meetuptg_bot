import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from meetbot.bot.constants import (
    BotState,
    CB_MAIN_MENU,
    CB_NETWORK_START,
    CB_NETWORK_SEARCH,
)
from meetbot.models import NetworkingMatchStatus

from meetbot.services.utils_bot import (
    _reply,
    _ensure_participant_async,
    _get_active_event_async,
    _get_profile_async,
    _start_matching,
    _send_search_menu,
    _send_with_markup,
    _create_match_async,
    _get_next_match_async,
    _get_or_create_profile_async,
    _send_match_card,
    _notify_waiting_async,
    _get_current_match_async,
)

logger = logging.getLogger(__name__)


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

        text = (
            f'Ваша анкета:\n'
            f'Роль: {profile.role}\n'
            f'Компания: {profile.company}\n'
            f'Стек: {profile.stack}\n'
            f'Интересы: {profile.interests}\n'
            f'Контакт: {profile.contact}'
        )

    markup = InlineKeyboardMarkup(buttons)

    if update.message:
        await update.message.reply_text(text, reply_markup=markup)
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=markup)


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

    await _reply(
        update,
        'Кто вы по роли? (например, backend, data, PM). /cancel для отмены.',
        show_menu=False,
    )
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

    if not (user and event):
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
        f'Анкета сохранена:\n'
        f'Роль: {profile.role}\n'
        f'Компания: {profile.company}\n'
        f'Стек: {profile.stack}\n'
        f'Интересы: {profile.interests}\n'
        f'Контакт: {profile.contact}\n'
        'Ищу для вас собеседника...'
    )

    target = await _get_next_match_async(profile)
    if not target:
        await _send_search_menu(
            update,
            'Вы первый в очереди. Напомню, когда появится ещё анкета.\n'
            'Можно вернуться в меню или попробовать поиск позже.',
        )
        await _notify_waiting_async(profile, context.application.bot)
        return ConversationHandler.END

    match = await _create_match_async(source_profile=profile, target_profile=target)
    context.user_data['current_match_id'] = match.id

    await _send_match_card(update, target, match)
    await _notify_waiting_async(profile, context.application.bot)

    return BotState.NETWORKING_MATCH


async def networking_accept(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    match = await _get_current_match_async(context)

    if not match:
        await _reply(update, 'Нет активного предложения. /start', show_menu=True)
        return ConversationHandler.END

    await _mark_match_status_async(match, NetworkingMatchStatus.ACCEPTED)

    await _reply(
        update,
        f'Свяжитесь с {match.target_profile.contact or "контактом"}. Удачного общения!',
        show_menu=True,
    )

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
            'Пока анкеты закончились. Как появятся новые — напомню.\n'
            'Можете вернуться в меню или попробовать позже.',
        )
        context.user_data.pop('current_match_id', None)
        return ConversationHandler.END

    new_match = await _create_match_async(source_profile=source_profile, target_profile=next_profile)
    context.user_data['current_match_id'] = new_match.id

    await _send_match_card(update, next_profile, new_match)
    return BotState.NETWORKING_MATCH


async def networking_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _send_search_menu(
        update,
        'Хорошо, остановил подбор. Вернуться в меню или попробовать ещё позже?',
    )
    context.user_data.pop('current_match_id', None)
    return ConversationHandler.END
