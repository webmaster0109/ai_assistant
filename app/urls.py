from django.urls import path
from . import views


urlpatterns = [
    path('', views.chat_convo, name='chat'),
    path('chat/', views.chat_post, name='chat_post'),
    # path('chat/voice/', views.voice_to_text, name="voice"),
    path('chat/history/<str:session_id>/', views.chat_history_conversations, name='chat_history'),
    path('chat/sessions/', views.chat_sessions, name='chat_sessions'),
    path('chat/delete/<str:session_id>/', views.delete_session, name='delete_session'),

    path('chat/api/<str:session_id>/', views.api_ai_message, name='api_ai_message'),
    path('api/usage-stats/', views.cloud_usage_stats, name='cloud_usage_stats'),
]
