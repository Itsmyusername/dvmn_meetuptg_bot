from django.contrib import admin
from .models import Participant, Place, Event, Question, Message
from dynamic_raw_id.admin import DynamicRawIDMixin


class ParticipantAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'subscriber',
        'organizer',
        'speaker',
        'tg_id'
    )
    list_filter = (
        'subscriber',
        'organizer',
        'speaker'
    )
    search_fields = ['tg_id']


class DonatAdmin(admin.ModelAdmin):
    list_display = (
        'donater',
        'size'
    )
    search_fields = [
        'donater'
    ]


class EventAdmin(DynamicRawIDMixin, admin.ModelAdmin):
    list_display = (
        'name',
        'place',
        'start',
        'finish',
        'active'
    )
    search_fields = [
        'name',
    ]
    list_filter = (
        'name',
        'speaker',
        'place',
        'start',
        'active'
    )
    # autocomplete_fields = ('speaker',)
    dynamic_raw_id_fields = ['speaker']


class QuestionAdmin(admin.ModelAdmin):
    list_display = (
        'author',
        'question',
        'event',
        'tg_chat_id'
    )
    search_fields = [
        'event',
    ]
    list_filter = (
        'event',
    )


class MessageAdmin(DynamicRawIDMixin, admin.ModelAdmin):
    list_display = (
        'message',
        'creation_date',
    )
    list_filter = (
        'creation_date',
    )
    search_fields = ['message']
    dynamic_raw_id_fields = ['recipent']


admin.site.register(Participant, ParticipantAdmin)
admin.site.register(Place)
admin.site.register(Event, EventAdmin)
admin.site.register(Question, QuestionAdmin)
admin.site.register(Message, MessageAdmin)