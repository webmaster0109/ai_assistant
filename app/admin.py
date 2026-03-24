from django.contrib import admin
from .models import ChatSession, ChatConversations, WebsiteSettings

# Register your models here.
class ChatSessionAdmin(admin.ModelAdmin):
  list_display = ('title', 'id', 'model', 'created_at')
  list_filter = ('model', 'created_at')
  search_fields = ('title', 'model')
  ordering = ('-created_at',)


admin.site.register(ChatSession, ChatSessionAdmin)

class ChatConversationsAdmin(admin.ModelAdmin):
  list_display = ('user_message', 'input_tokens', 'output_tokens')
  list_filter = ('session__model', 'created_at')
  search_fields = ('user_message', 'ai_message')
  ordering = ('-created_at',)
  readonly_fields = ('input_tokens', 'output_tokens')

admin.site.register(ChatConversations, ChatConversationsAdmin)


class WebsiteSettingsAdmin(admin.ModelAdmin):
  list_display = ('website_name', 'maintainance_mode')

admin.site.register(WebsiteSettings, WebsiteSettingsAdmin)