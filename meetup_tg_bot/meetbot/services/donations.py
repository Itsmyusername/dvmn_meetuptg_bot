import uuid
from decimal import Decimal

from django.conf import settings

from meetbot.models import Donation, DonationStatus, Event, Participant


class DonationError(Exception):
    """Ошибка при создании или обновлении платежа."""


def _ensure_yookassa():
    if not (settings.YOOKASSA_SHOP_ID and settings.YOOKASSA_SECRET_KEY):
        raise DonationError('ЮKassa не настроена: задайте YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY')


def create_donation(*, participant: Participant | None, event: Event, amount: Decimal, description: str) -> Donation:
    return Donation.objects.create(
        participant=participant,
        event=event,
        amount=amount,
        currency='RUB',
        status=DonationStatus.PENDING,
        description=description,
    )


def create_yookassa_payment(donation: Donation) -> Donation:
    """
    Создаёт платеж в ЮKassa и сохраняет его данные в Donation.
    """
    _ensure_yookassa()
    from yookassa import Configuration, Payment

    Configuration.account_id = settings.YOOKASSA_SHOP_ID
    Configuration.secret_key = settings.YOOKASSA_SECRET_KEY

    amount_value = str(donation.amount.quantize(Decimal('0.01')))
    idempotence_key = str(uuid.uuid4())

    return_url = settings.YOOKASSA_RETURN_URL or 'https://t.me'
    description = donation.description or f'Поддержка митапа {donation.event.name}'

    payload = {
        "amount": {"value": amount_value, "currency": donation.currency},
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": return_url,
        },
        "metadata": {
            "donation_id": donation.id,
            "event_id": donation.event_id,
        },
        "description": description[:127],
    }

    payment = Payment.create(payload, idempotence_key)

    donation.provider = 'yookassa'
    donation.yookassa_payment_id = payment.id
    donation.idempotence_key = idempotence_key
    donation.confirmation_url = getattr(payment.confirmation, 'confirmation_url', '') or ''
    donation.status = _map_status(payment.status)
    donation.save(update_fields=['provider', 'yookassa_payment_id', 'idempotence_key', 'confirmation_url', 'status'])
    return donation


def refresh_payment_status(donation: Donation) -> Donation:
    """Запрашивает статус платежа в ЮKassa."""
    if not donation.yookassa_payment_id:
        return donation
    _ensure_yookassa()
    from yookassa import Configuration, Payment

    Configuration.account_id = settings.YOOKASSA_SHOP_ID
    Configuration.secret_key = settings.YOOKASSA_SECRET_KEY

    payment = Payment.find_one(donation.yookassa_payment_id)
    donation.status = _map_status(payment.status)
    donation.save(update_fields=['status'])
    return donation


def _map_status(payment_status: str) -> str:
    mapping = {
        'pending': DonationStatus.PENDING,
        'waiting_for_capture': DonationStatus.WAITING_FOR_CAPTURE,
        'succeeded': DonationStatus.SUCCEEDED,
        'canceled': DonationStatus.CANCELED,
    }
    return mapping.get(payment_status, DonationStatus.PENDING)
