from enum import IntEnum


# Команды бота
CMD_START = 'start'
CMD_HELP = 'help'
CMD_PROGRAM = 'program'
CMD_ASK = 'ask'
CMD_NETWORKING = 'networking'
CMD_DONATE = 'donate'
CMD_SUBSCRIBE = 'subscribe'
CMD_HEALTH = 'health'
CMD_CANCEL = 'cancel'

# Callback data для главного меню
CB_PROGRAM = 'menu_program'
CB_QUESTION = 'menu_question'
CB_NETWORKING = 'menu_networking'
CB_DONATE = 'menu_donate'
CB_SUBSCRIBE = 'menu_subscribe'
CB_MAIN_MENU = 'menu_main'
CB_NETWORK_START = 'network_start'
CB_NETWORK_SEARCH = 'network_search'
CB_MATCH_ACCEPT = 'match_accept'
CB_MATCH_SKIP = 'match_skip'
CB_MATCH_STOP = 'match_stop'


class BotState(IntEnum):
    ASK_TEXT = 1
    NETWORKING_ROLE = 2
    NETWORKING_COMPANY = 3
    NETWORKING_STACK = 4
    NETWORKING_INTERESTS = 5
    NETWORKING_CONTACT = 6
    NETWORKING_MATCH = 7
    DONATE_AMOUNT = 8
    SUBSCRIBE_CHOICE = 9
