from django.contrib import admin

from .models import (
    BackgroundJob,
    ChatConversations,
    ChatDocument,
    ChatDocumentChunk,
    ChatImage,
    ChatSession,
    LearningQuizQuestion,
    LearningQuizSession,
    WebsiteSettings,
)


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "owner",
        "model",
        "is_pinned",
        "is_public",
        "created_at",
        "updated_at",
    )
    list_filter = ("model", "is_pinned", "is_public", "created_at", "owner")
    search_fields = ("id", "title", "model", "owner__username", "owner__email", "share_token")
    ordering = ("-updated_at",)


@admin.register(ChatDocument)
class ChatDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "filename",
        "session",
        "is_active",
        "processing_status",
        "extracted_characters",
        "uploaded_at",
    )
    list_filter = ("is_active", "processing_status", "uploaded_at", "session__model", "session__owner")
    search_fields = ("filename", "session__title", "session__owner__username", "file_hash")
    ordering = ("-uploaded_at",)
    readonly_fields = (
        "file_hash",
        "extracted_characters",
        "processing_status",
        "processing_error",
        "uploaded_at",
    )


@admin.register(ChatDocumentChunk)
class ChatDocumentChunkAdmin(admin.ModelAdmin):
    list_display = ("document", "chunk_index", "page_number", "short_content")
    list_filter = ("page_number", "document__session__model", "document__session__owner")
    search_fields = (
        "content",
        "document__filename",
        "document__session__title",
        "document__session__owner__username",
    )
    ordering = ("document", "chunk_index")

    def short_content(self, obj):
        return obj.content[:100]

    short_content.short_description = "Content"


@admin.register(ChatImage)
class ChatImageAdmin(admin.ModelAdmin):
    list_display = (
        "filename",
        "session",
        "content_type",
        "is_active",
        "uploaded_at",
    )
    list_filter = ("is_active", "uploaded_at", "content_type", "session__model", "session__owner")
    search_fields = ("filename", "session__title", "session__owner__username", "file_hash")
    ordering = ("-uploaded_at",)
    readonly_fields = ("file_hash", "uploaded_at", "content_type")


@admin.register(ChatConversations)
class ChatConversationsAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "image_attachment",
        "short_user_message",
        "input_tokens",
        "output_tokens",
        "created_at",
    )
    list_filter = ("session__model", "created_at", "session__owner")
    search_fields = ("user_message", "ai_message", "session__owner__username", "session__title")
    ordering = ("-created_at",)
    readonly_fields = ("input_tokens", "output_tokens", "created_at", "updated_at")

    def short_user_message(self, obj):
        return obj.user_message[:80]

    short_user_message.short_description = "User message"


@admin.register(LearningQuizSession)
class LearningQuizSessionAdmin(admin.ModelAdmin):
    list_display = (
        "topic",
        "owner",
        "model",
        "difficulty_level",
        "correct_answers",
        "total_questions",
        "completed_at",
        "created_at",
    )
    list_filter = ("model", "difficulty_level", "completed_at", "created_at", "owner")
    search_fields = ("topic", "owner__username", "owner__email", "difficulty_level")
    ordering = ("-created_at",)


@admin.register(LearningQuizQuestion)
class LearningQuizQuestionAdmin(admin.ModelAdmin):
    list_display = ("quiz_session", "sort_order", "short_question", "correct_option", "selected_option", "is_correct")
    list_filter = ("correct_option", "selected_option", "is_correct", "quiz_session__owner", "quiz_session__model")
    search_fields = ("question_text", "explanation", "quiz_session__topic", "quiz_session__owner__username")
    ordering = ("quiz_session", "sort_order")

    def short_question(self, obj):
        return obj.question_text[:100]

    short_question.short_description = "Question"


@admin.register(BackgroundJob)
class BackgroundJobAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "owner",
        "kind",
        "status",
        "session",
        "document",
        "created_at",
        "finished_at",
    )
    list_filter = ("kind", "status", "created_at", "owner")
    search_fields = ("id", "title", "owner__username", "session__title", "document__filename")
    ordering = ("-created_at",)
    readonly_fields = (
        "payload",
        "result",
        "error_message",
        "created_at",
        "started_at",
        "finished_at",
    )


@admin.register(WebsiteSettings)
class WebsiteSettingsAdmin(admin.ModelAdmin):
    list_display = ("website_name", "maintainance_mode")
    fieldsets = (
        (
            "General",
            {
                "fields": (
                    "website_name",
                    "website_description",
                    "website_logo",
                    "website_favicon",
                )
            },
        ),
        (
            "Maintenance",
            {
                "fields": ("maintainance_mode",),
                "description": "Yahan se website ka maintenance mode on/off karo.",
            },
        ),
        (
            "AI Configuration",
            {
                "fields": ("system_prompt",),
                "description": "Yahan se AI ka behavior customize karo.",
            },
        ),
    )
