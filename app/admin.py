from django.contrib import admin
from .models import ChatSession, ChatConversations

# Register your models here.
class ChatSessionAdmin(admin.ModelAdmin):
  list_display = ('title', 'id', 'model', 'created_at')
  list_filter = ('model', 'created_at')
  search_fields = ('title', 'model')
  ordering = ('-created_at',)


admin.site.register(ChatSession, ChatSessionAdmin)
admin.site.register(ChatConversations)
