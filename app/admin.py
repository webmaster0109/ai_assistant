from django.contrib import admin
from .models import ChatSession, ChatConversations, WebsiteSettings

# Register your models here.
class ChatSessionAdmin(admin.ModelAdmin):
  list_display = ('title', 'id', 'model', 'created_at')
  list_filter = ('model', 'created_at')
  search_fields = ('title', 'model')
  ordering = ('-created_at',)


admin.site.register(ChatSession, ChatSessionAdmin)
admin.site.register(ChatConversations)


class WebsiteSettingsAdmin(admin.ModelAdmin):
  list_display = ('website_name', 'maintainance_mode')

admin.site.register(WebsiteSettings, WebsiteSettingsAdmin)