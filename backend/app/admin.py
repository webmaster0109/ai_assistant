from django.contrib import admin
from .models import ChatSession, ChatConversations, WebsiteSettings

# Register your models here.
class ChatSessionAdmin(admin.ModelAdmin):
  list_display = ('title', 'owner', 'id', 'model', 'created_at')
  list_filter = ('model', 'created_at', 'owner')
  search_fields = ('title', 'model', 'owner__username', 'owner__email')
  ordering = ('-created_at',)


admin.site.register(ChatSession, ChatSessionAdmin)

class ChatConversationsAdmin(admin.ModelAdmin):
  list_display = ('session', 'short_user_message', 'input_tokens', 'output_tokens')
  list_filter = ('session__model', 'created_at', 'session__owner')
  search_fields = ('user_message', 'ai_message', 'session__owner__username', 'session__title')
  ordering = ('-created_at',)
  readonly_fields = ('input_tokens', 'output_tokens')

  def short_user_message(self, obj):
    return obj.user_message[:80]

  short_user_message.short_description = 'User message'

admin.site.register(ChatConversations, ChatConversationsAdmin)


class WebsiteSettingsAdmin(admin.ModelAdmin):
  list_display = ('website_name', 'maintainance_mode')
  fieldsets = (
        ("General", {
            "fields": ("website_name", "website_description", "website_favicon")
        }),
        (
          "Maintenance", {
            "fields": ("maintainance_mode",),
            "description": "Yahan se website ka maintenance mode on/off karo."
          }
        ),
        ("AI Configuration", {
            "fields": ("system_prompt",),
            "description": "Yahan se AI ka behavior customize karo."
        }),
    )

admin.site.register(WebsiteSettings, WebsiteSettingsAdmin)
