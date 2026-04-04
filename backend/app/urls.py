from django.urls import path
from . import views


urlpatterns = [
    path('', views.app_shell, name='app_shell'),
    path('api/auth/me/', views.auth_status, name='auth_status'),
    path('api/auth/register/', views.register_user, name='register_user'),
    path('api/auth/login/', views.login_user, name='login_user'),
    path('api/auth/logout/', views.logout_user, name='logout_user'),
    path('api/models/', views.models_catalog, name='models_catalog'),
    path('api/chat/', views.chat_post, name='chat_post'),
    path('api/chat/sessions/', views.chat_sessions, name='chat_sessions'),
    path('api/chat/sessions/<str:session_id>/', views.delete_session, name='delete_session'),
    path('api/chat/sessions/<str:session_id>/messages/', views.chat_history_conversations, name='chat_history'),
    path('api/usage-stats/', views.cloud_usage_stats, name='cloud_usage_stats'),
]
