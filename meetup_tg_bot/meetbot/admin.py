from django.contrib import admin

from .models import (
    Donation,
    Event,
    NetworkingMatch,
    NetworkingProfile,
    Participant,
    Place,
    Question,
    Subscription,
    Talk,
    SpeakerApplication,
)


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'first_name',
        'last_name',
        'tg_username',
        'is_speaker',
        'is_organizer',
        'created_at',
    )
    search_fields = ('first_name', 'last_name', 'tg_username', 'tg_id')
    list_filter = ('is_speaker', 'is_organizer', 'wants_notifications')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'address')
    search_fields = ('name', 'address')


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'name',
        'start_at',
        'end_at',
        'place',
        'is_active',
        'is_published',
    )
    list_filter = ('is_active', 'is_published', 'place')
    search_fields = ('name',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Talk)
class TalkAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'title',
        'event',
        'speaker',
        'start_at',
        'status',
        'is_current',
    )
    list_filter = ('status', 'is_current', 'event')
    search_fields = ('title', 'speaker__first_name', 'speaker__last_name', 'speaker__tg_username')
    ordering = ('event', 'order', 'start_at')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('id', 'talk', 'author', 'status', 'asked_at')
    list_filter = ('status', 'talk__event')
    search_fields = ('text', 'author__first_name', 'author__last_name', 'author__tg_username')
    readonly_fields = ('asked_at', 'answered_at')
    ordering = ('-asked_at',)


@admin.register(NetworkingProfile)
class NetworkingProfileAdmin(admin.ModelAdmin):
    list_display = ('id', 'participant', 'event', 'role', 'is_active', 'created_at')
    list_filter = ('event', 'is_active')
    search_fields = (
        'participant__first_name',
        'participant__last_name',
        'participant__tg_username',
        'role',
        'stack',
    )
    readonly_fields = ('created_at', 'updated_at')


@admin.register(NetworkingMatch)
class NetworkingMatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'event', 'source_profile', 'target_profile', 'status', 'created_at')
    list_filter = ('status', 'event')
    search_fields = (
        'source_profile__participant__tg_username',
        'target_profile__participant__tg_username',
    )
    readonly_fields = ('created_at', 'responded_at')


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = ('id', 'event', 'participant', 'amount', 'currency', 'status', 'created_at')
    list_filter = ('status', 'currency', 'event')
    search_fields = (
        'participant__first_name',
        'participant__last_name',
        'participant__tg_username',
    )
    readonly_fields = ('created_at',)


@admin.register(SpeakerApplication)
class SpeakerApplicationAdmin(admin.ModelAdmin):
    list_display = ('id', 'participant', 'event', 'topic', 'status', 'created_at')
    list_filter = ('status', 'event')
    search_fields = ('topic', 'contact', 'participant__tg_username', 'participant__first_name', 'participant__last_name')
    readonly_fields = ('created_at', 'updated_at')

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'participant', 'event', 'subscription_type', 'is_active', 'created_at')
    list_filter = ('subscription_type', 'is_active', 'event')
    search_fields = (
        'participant__first_name',
        'participant__last_name',
        'participant__tg_username',
    )
    readonly_fields = ('created_at',)
