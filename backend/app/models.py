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
    is_pinned = models.BooleanField(default=False)
    is_public = models.BooleanField(default=False)
    share_token = models.CharField(max_length=64, blank=True, null=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["owner", "-updated_at"], name="app_chatses_owner_i_79aaa6_idx"),
        ]

    def __str__(self):
        return f"{self.owner} - {self.model} - {self.title}"

    def get_documents(self):
        prefetched = getattr(self, "_prefetched_objects_cache", {}).get("documents")
        if prefetched is not None:
            return sorted(prefetched, key=lambda item: (not item.is_active, -item.uploaded_at.timestamp()))
        return list(self.documents.order_by("-is_active", "-uploaded_at"))

    def get_active_document(self):
        for document in self.get_documents():
            if document.is_active:
                return document
        return None


class ChatDocument(models.Model):
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    file = models.FileField(upload_to="chat_documents/")
    filename = models.CharField(max_length=255)
    file_hash = models.CharField(max_length=64, blank=True, default="")
    is_active = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    extracted_characters = models.IntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["session", "-is_active", "-uploaded_at"], name="app_chatdoc_sess_a_idx"),
            models.Index(fields=["session", "file_hash"], name="app_chatdoc_sess_f_idx"),
        ]

    def __str__(self):
        return self.filename


class ChatDocumentChunk(models.Model):
    document = models.ForeignKey(
        ChatDocument,
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    chunk_index = models.PositiveIntegerField()
    page_number = models.PositiveIntegerField(null=True, blank=True)
    content = models.TextField()

    class Meta:
        indexes = [
            models.Index(fields=["document", "chunk_index"], name="app_doc_chunk_idx"),
        ]
        ordering = ["chunk_index"]

    def __str__(self):
        return f"{self.document.filename} #{self.chunk_index}"

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
