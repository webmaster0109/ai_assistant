import uuid
from django.conf import settings
from django.db import models

def generate_uuid():
    return str(uuid.uuid4()).replace("-", "")

class ChatSession(models.Model):
    id = models.CharField(primary_key=True, default=generate_uuid, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_sessions",
    )
    model = models.CharField(max_length=100)
    title = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["owner", "-updated_at"], name="app_chatses_owner_i_79aaa6_idx"),
        ]

    def __str__(self):
        return f"{self.owner} - {self.model} - {self.title}"

class ChatConversations(models.Model):
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="conversations"
    )
    user_message = models.TextField()
    ai_message = models.TextField()
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["session", "-created_at"]),
        ]

    def __str__(self):
        return self.user_message[:80]


class WebsiteSettings(models.Model):
    website_name = models.CharField(max_length=100, default="Ollama AI")
    website_logo = models.ImageField(upload_to='logos/', null=True, blank=True)
    website_favicon = models.ImageField(upload_to='favicons/', null=True, blank=True)
    website_description = models.TextField(default="A powerful AI chatbot platform built with Django and Ollama API.")

    system_prompt = models.TextField(
        blank=True,
        default="You are a helpful and precise assistant for answering user queries. Always use all available information to provide the best answer. If you don't know the answer, say you don't know. Be concise and clear in your responses."
    )

    maintainance_mode = models.BooleanField(default=False)

    def __str__(self):
        return self.website_name

    class Meta:
        verbose_name = "Website Settings"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from django.core.cache import cache
        cache.delete("system_prompt")
