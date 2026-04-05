from django.urls import path
from . import views


urlpatterns = [
    path('', views.app_shell, name='app_shell'),
    path('share/<str:share_token>/', views.app_shell, name='shared_app_shell'),
    path('sw.js', views.service_worker, name='service_worker'),
    path('manifest.webmanifest', views.web_manifest, name='web_manifest'),
    path('api/auth/me/', views.auth_status, name='auth_status'),
    path('api/auth/register/', views.register_user, name='register_user'),
    path('api/auth/login/', views.login_user, name='login_user'),
    path('api/auth/logout/', views.logout_user, name='logout_user'),
    path('api/models/', views.models_catalog, name='models_catalog'),
    path('api/chat/', views.chat_post, name='chat_post'),
    path('api/chat/documents/', views.upload_chat_document, name='upload_chat_document'),
    path(
        'api/chat/sessions/<str:session_id>/documents/<int:document_id>/select/',
        views.select_chat_document,
        name='select_chat_document',
    ),
    path('api/chat/stream/', views.chat_stream, name='chat_stream'),
    path('api/chat/streams/<str:stream_id>/stop/', views.stop_chat_stream, name='stop_chat_stream'),
    path('api/chat/sessions/', views.chat_sessions, name='chat_sessions'),
    path('api/chat/sessions/<str:session_id>/', views.delete_session, name='delete_session'),
    path('api/chat/sessions/<str:session_id>/pin/', views.toggle_session_pin, name='toggle_session_pin'),
    path('api/chat/sessions/<str:session_id>/share/', views.toggle_session_visibility, name='toggle_session_visibility'),
    path('api/chat/sessions/<str:session_id>/messages/', views.chat_history_conversations, name='chat_history'),
    path(
        'api/chat/sessions/<str:session_id>/messages/<int:conversation_id>/edit/',
        views.edit_message,
        name='edit_message',
    ),
    path(
        'api/chat/sessions/<str:session_id>/messages/<int:conversation_id>/regenerate/',
        views.regenerate_message,
        name='regenerate_message',
    ),
    path('api/usage-stats/', views.cloud_usage_stats, name='cloud_usage_stats'),
    path('api/usage-stats/models/', views.cloud_usage_by_model, name='cloud_usage_by_model'),
    path('api/public/chat/<str:share_token>/', views.public_chat_history, name='public_chat_history'),
]
