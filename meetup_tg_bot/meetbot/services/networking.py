from typing import Optional

from django.db import transaction

from django.db.models import Count
from meetbot.models import NetworkingMatch, NetworkingMatchStatus, NetworkingProfile, Participant, Event


def get_or_create_profile(
    *,
    participant: Participant,
    event: Event,
    role: str,
    company: str,
    stack: str,
    interests: str,
    contact: str,
) -> NetworkingProfile:
    """Создаёт или обновляет анкету участника на событие."""
    profile, _ = NetworkingProfile.objects.update_or_create(
        participant=participant,
        event=event,
        defaults={
            'role': role,
            'company': company,
            'stack': stack,
            'interests': interests,
            'contact': contact,
            'is_active': True,
        },
    )
    return profile


def get_next_match(source_profile: NetworkingProfile) -> Optional[NetworkingProfile]:
    """
    Возвращает следующую анкету для знакомства
    """
    seen_target_ids = NetworkingMatch.objects.filter(
        event=source_profile.event,
        source_profile=source_profile,
    ).values_list('target_profile_id', flat=True)

    return (
        NetworkingProfile.objects.filter(
            event=source_profile.event,
            is_active=True,
        )
        .exclude(id=source_profile.id)
        .exclude(id__in=seen_target_ids)
        .order_by('created_at')
        .first()
    )


@transaction.atomic
def create_match(
    *,
    source_profile: NetworkingProfile,
    target_profile: NetworkingProfile,
    status: str = NetworkingMatchStatus.PENDING,
) -> NetworkingMatch:
    """Создаёт запись о выдаче анкеты."""
    match, _ = NetworkingMatch.objects.get_or_create(
        event=source_profile.event,
        source_profile=source_profile,
        target_profile=target_profile,
        defaults={'status': status},
    )
    return match


def mark_match_status(match: NetworkingMatch, status: str) -> NetworkingMatch:
    """Обновляет статус для мэтча."""
    match.status = status
    match.save(update_fields=['status'])
    return match


def get_waiting_profile(new_profile: NetworkingProfile) -> Optional[NetworkingProfile]:
    """Ищет пользователя, у которого еще не было отправленных мэтчей"""
    return (
        NetworkingProfile.objects.filter(event=new_profile.event, is_active=True)
        .annotate(sent_count=Count('sent_matches'))
        .filter(sent_count=0)
        .exclude(id=new_profile.id)
        .order_by('created_at')
        .first()
    )


def count_profiles_for_event(event: Event) -> int:
    return NetworkingProfile.objects.filter(event=event, is_active=True).count()


def get_profile(participant: Participant, event: Event) -> Optional[NetworkingProfile]:
    return NetworkingProfile.objects.filter(participant=participant, event=event, is_active=True).first()
