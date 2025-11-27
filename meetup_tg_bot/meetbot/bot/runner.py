import logging

from django.conf import settings
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from .handlers import handle_menu_callback, start, unknown_command

logger = logging.getLogger(__name__)


def build_application(token: str) -> Application:
    
    application = ApplicationBuilder().token(token).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CallbackQueryHandler(handle_menu_callback, pattern='^menu_'))
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    return application


def run_bot() -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError('TELEGRAM_BOT_TOKEN не задан в переменных окружения')

    logger.info('Starting Telegram bot...')
    application = build_application(settings.TELEGRAM_BOT_TOKEN)
    application.run_polling(allowed_updates=None)


if __name__ == '__main__':
    run_bot()