from asgiref.sync import sync_to_async
from django.apps import apps
from django.utils import timezone


@sync_to_async
def get_program_text() -> str:
    Event = apps.get_model('meetbot', 'Event')
    Talk = apps.get_model('meetbot', 'Talk')

    now = timezone.now()

    # активное
    current_events = list(
        Event.objects.filter(
            is_published=True,
            start_at__lte=now,
            end_at__gte=now,
        ).order_by('start_at')
    )

    # будущие
    future_events = list(
        Event.objects.filter(
            is_published=True,
            start_at__gt=now,
        ).order_by('start_at')
    )

    # заглушка
    if not current_events and not future_events:
        return 'Нет текущих или будущих мероприятий!'

    lines = []

    # вывод активного
    if current_events:
        lines.append('!!! *СЕЙЧАС ПРОХОДИТ:*')
        lines.append('')
        for event in current_events:
            lines.extend(render_event_block(event))
            lines.append('')

    # вывод будущих
    if future_events:
        lines.append('📅 *БУДУЩИЕ МЕРОПРИЯТИЯ:*')
        lines.append('')
        for event in future_events:
            lines.extend(render_event_block(event))
            lines.append('')

    return '\n'.join(lines).strip()


def render_event_block(event):
    Talk = apps.get_model('meetbot', 'Talk')
    lines = []

    tz = timezone.get_current_timezone()

    start_local = event.start_at.astimezone(tz)
    end_local = event.end_at.astimezone(tz)

    lines.append(f'*✦ ТЕМА ИВЕНТА:* 🎉 *{event.name}*')
    lines.append(f"   *Дата: {start_local.strftime('%d.%m.%y')}*")
    lines.append(f"   *Время:* 🕒 *{start_local.strftime('%H:%M')}* — *{end_local.strftime('%H:%M')}*")

    if event.place:
        lines.append(f"   *Адрес:* 📍{event.place.name}, {event.place.address}")

    talks = Talk.objects.filter(event=event).order_by('order', 'start_at')

    if not talks.exists():
        lines.append('  └ Программа пока не заполнена.')
        return lines

    lines.append('')
    lines.append('   🎤 *Доклады:*')

    for talk in talks:
        talk_start_local = talk.start_at.astimezone(tz)
        t = talk_start_local.strftime('%H:%M')

        speaker = talk.speaker or 'спикер не указан'
        if not isinstance(speaker, str):
            speaker = str(speaker)

        cancelled_suffix = ' *(❌ отменён)*' if talk.status == 'cancelled' else ''

        lines.append('   ─────────────────')
        lines.append(f'   • {cancelled_suffix} *{t}* — {talk.title}')
        lines.append(f'   *Спикер:*    👤 {speaker}')

    return lines