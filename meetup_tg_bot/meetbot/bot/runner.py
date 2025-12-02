import logging

import django
from django.conf import settings
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .constants import (
    CB_DONATE,
    CB_NETWORKING,
    CB_NETWORK_START,
    CB_NETWORK_SEARCH,
    CB_ORGANIZER_MENU,
    CB_PROGRAM,
    CB_QUESTION,
    CB_SPEAKER_MENU,
    CB_SUBSCRIBE,
    CB_SUBSCRIBE_EVENT,
    CB_SUBSCRIBE_FUTURE,
    CB_DONATE_PAY_PREFIX,
    CB_DONATE_STATUS_PREFIX,
    CB_TALK_FINISH_PREFIX,
    CB_TALK_START_PREFIX,
    CB_MATCH_ACCEPT,
    CB_MATCH_SKIP,
    CB_MATCH_STOP,
    CMD_ASK,
    CMD_ANNOUNCE,
    CMD_DONATE,
    CMD_HEALTH,
    CMD_NETWORKING,
    CMD_ORGANIZER,
    CMD_PROGRAM,
    CMD_SPEAKER,
    CMD_START,
    CMD_SUBSCRIBE,
    CMD_CANCEL,
    BotState,
)

logger = logging.getLogger(__name__)


def build_application(token: str) -> Application:
    """Создает Telegram Application с базовыми хендлерами."""
    
    from .handlers import (
        ask_save,
        ask_start,
        cancel,
        donate_amount,
        donate_start,
        handle_menu_callback,
        health,
        networking_accept,
        networking_contact,
        networking_company,
        networking_interests,
        networking_role,
        networking_skip,
        networking_stack,
        networking_start,
        networking_stop,
        subscribe_toggle_event,
        subscribe_toggle_future,
        donate_pay_callback,
        donate_status,
        organizer_menu,
        organizer_show_questions,
        program,
        start,
        speaker_menu,
        subscribe,
        talk_finish,
        talk_start,
        announce_start,
        announce_send,
        unknown_command,
    )

    application = ApplicationBuilder().token(token).build()

    application.add_handler(CommandHandler(CMD_START, start))
    application.add_handler(CommandHandler(CMD_PROGRAM, program))
    application.add_handler(CommandHandler(CMD_HEALTH, health))
    application.add_handler(CommandHandler(CMD_SPEAKER, speaker_menu))
    application.add_handler(CommandHandler(CMD_ORGANIZER, organizer_menu))

    application.add_handler(
        CallbackQueryHandler(
            handle_menu_callback,
            pattern='^menu_(program|question|networking|donate|subscribe|speaker|organizer|main)$',
        ),
        group=0,
    )
    application.add_handler(
        CallbackQueryHandler(organizer_show_questions, pattern='^org_show_question$'),
        group=0,
    )
    application.add_handler(CallbackQueryHandler(talk_start, pattern=f'^{CB_TALK_START_PREFIX}\\d+$'), group=0)
    application.add_handler(CallbackQueryHandler(talk_finish, pattern=f'^{CB_TALK_FINISH_PREFIX}\\d+$'), group=0)
    application.add_handler(CallbackQueryHandler(donate_pay_callback, pattern=f'^{CB_DONATE_PAY_PREFIX}\\d+$'), group=0)
    application.add_handler(CallbackQueryHandler(donate_status, pattern=f'^{CB_DONATE_STATUS_PREFIX}\\d+$'), group=0)
    application.add_handler(CallbackQueryHandler(subscribe_toggle_event, pattern=f'^{CB_SUBSCRIBE_EVENT}$'), group=0)
    application.add_handler(CallbackQueryHandler(subscribe_toggle_future, pattern=f'^{CB_SUBSCRIBE_FUTURE}$'), group=0)

    ask_conv = ConversationHandler(
        entry_points=[
            CommandHandler(CMD_ASK, ask_start),
            CallbackQueryHandler(ask_start, pattern=f'^{CB_QUESTION}$'),
            CallbackQueryHandler(ask_start, pattern='^talk_select_\\d+$'),
        ],
        states={
            BotState.ASK_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_save)],
        },
        fallbacks=[CommandHandler(CMD_CANCEL, cancel)],
        allow_reentry=True,
    )

    announce_conv = ConversationHandler(
        entry_points=[CommandHandler(CMD_ANNOUNCE, announce_start)],
        states={
            BotState.ANNOUNCE_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, announce_send)],
        },
        fallbacks=[CommandHandler(CMD_CANCEL, cancel)],
        allow_reentry=True,
    )

    networking_conv = ConversationHandler(
        entry_points=[
            CommandHandler(CMD_NETWORKING, networking_start),
            CallbackQueryHandler(networking_start, pattern=f'^{CB_NETWORK_START}$'),
            CallbackQueryHandler(networking_start, pattern=f'^{CB_NETWORK_SEARCH}$'),
        ],
        states={
            BotState.NETWORKING_ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, networking_role)],
            BotState.NETWORKING_COMPANY: [MessageHandler(filters.TEXT & ~filters.COMMAND, networking_company)],
            BotState.NETWORKING_STACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, networking_stack)],
            BotState.NETWORKING_INTERESTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, networking_interests)],
            BotState.NETWORKING_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, networking_contact)],
            BotState.NETWORKING_MATCH: [
                CallbackQueryHandler(networking_accept, pattern=f'^{CB_MATCH_ACCEPT}$'),
                CallbackQueryHandler(networking_skip, pattern=f'^{CB_MATCH_SKIP}$'),
                CallbackQueryHandler(networking_stop, pattern=f'^{CB_MATCH_STOP}$'),
            ],
        },
        fallbacks=[CommandHandler(CMD_CANCEL, cancel)],
        allow_reentry=True,
    )

    application.add_handler(ask_conv, group=1)
    application.add_handler(networking_conv, group=1)
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler(CMD_DONATE, donate_start)],
            states={BotState.DONATE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, donate_amount)]},
            fallbacks=[CommandHandler(CMD_CANCEL, cancel)],
            allow_reentry=True,
        ),
        group=1,
    )
    application.add_handler(CommandHandler(CMD_SUBSCRIBE, subscribe), group=1)
    application.add_handler(announce_conv, group=1)

    # фикс неизвестные команды
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    return application


def run_bot() -> None:
    
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError('TELEGRAM_BOT_TOKEN не задан в переменных окружения')

    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )
    logger.info('Starting Telegram bot...')
    logger.info('Allowed updates: %s', Update.ALL_TYPES)

    
    django.setup()

    application = build_application(settings.TELEGRAM_BOT_TOKEN)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    run_bot()
