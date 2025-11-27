from typing import Optional

from django.utils import timezone

from django.db import transaction

from meetbot.models import Event, Question, QuestionStatus, Talk, TalkStatus, Participant


def get_current_talk(event: Event) -> Optional[Talk]:
    """Возвращает текущий доклад:  is_current → статус → по времени → последний начавшийся."""
    if not event:
        return None

    active_qs = event.talks.select_related('speaker').exclude(status__in=[TalkStatus.DONE, TalkStatus.CANCELLED])

    if event.current_talk_id:
        talk = event.talks.select_related('speaker').filter(id=event.current_talk_id).first()
        if talk and talk.status not in (TalkStatus.DONE, TalkStatus.CANCELLED):
            return talk

    talk = active_qs.filter(is_current=True).order_by('-start_at').first()
    if talk:
        return talk

    talk = active_qs.filter(status=TalkStatus.IN_PROGRESS).order_by('-start_at').first()
    if talk:
        return talk

    now = timezone.now()
    talk = active_qs.filter(start_at__lte=now, end_at__gte=now).order_by('start_at').first()
    if talk:
        return talk

    return active_qs.filter(start_at__lte=now).order_by('-start_at').first()


def get_next_talk(event: Event) -> Optional[Talk]:
    if not event:
        return None
    now = timezone.now()
    return event.talks.select_related('speaker').filter(start_at__gt=now).order_by('start_at').first()


def create_question(*, talk: Talk, author: Participant | None, text: str) -> Question:
    return Question.objects.create(talk=talk, author=author, text=text, status=QuestionStatus.PENDING)


@transaction.atomic
def start_talk(talk: Talk) -> Talk:
    """Делает доклад текущим и ставит статус IN_PROGRESS, снимая прошлый."""
    event = talk.event
    prev = None
    if event.current_talk_id and event.current_talk_id != talk.id:
        try:
            prev = event.talks.select_for_update().get(id=event.current_talk_id)
        except Talk.DoesNotExist:
            prev = None

    if prev:
        prev.is_current = False
        if prev.status == TalkStatus.IN_PROGRESS:
            prev.status = TalkStatus.DONE
        prev.save(update_fields=['is_current', 'status'])

    event.current_talk = talk
    event.save(update_fields=['current_talk'])

    event.talks.exclude(id=talk.id).update(is_current=False)
    talk.is_current = True
    talk.status = TalkStatus.IN_PROGRESS
    talk.save(update_fields=['is_current', 'status'])
    return talk


@transaction.atomic
def finish_talk(talk: Talk) -> Talk:
    """Отмечает доклад завершенным и снимает его из текущих."""
    event = talk.event
    talk.is_current = False
    if talk.status != TalkStatus.CANCELLED:
        talk.status = TalkStatus.DONE
    talk.save(update_fields=['is_current', 'status'])

    if event.current_talk_id == talk.id:
        event.current_talk = None
        event.save(update_fields=['current_talk'])
    return talk
