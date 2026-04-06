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

    def get_images(self):
        prefetched = getattr(self, "_prefetched_objects_cache", {}).get("images")
        if prefetched is not None:
            return sorted(
                prefetched,
                key=lambda item: (
                    not item.is_active,
                    item.activated_at.timestamp() if item.is_active and item.activated_at else float("inf"),
                    -item.uploaded_at.timestamp() if not item.is_active else 0,
                ),
            )
        return list(self.images.order_by("-is_active", "activated_at", "-uploaded_at"))

    def get_active_image(self):
        active_images = self.get_active_images()
        return active_images[0] if active_images else None

    def get_active_images(self):
        return [image for image in self.get_images() if image.is_active]


class ChatDocument(models.Model):
    STATUS_QUEUED = "queued"
    STATUS_PROCESSING = "processing"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_QUEUED, "Queued"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_READY, "Ready"),
        (STATUS_FAILED, "Failed"),
    )

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
    processing_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_QUEUED,
    )
    processing_error = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["session", "-is_active", "-uploaded_at"], name="app_chatdoc_sess_a_idx"),
            models.Index(fields=["session", "file_hash"], name="app_chatdoc_sess_f_idx"),
        ]

    def __str__(self):
        return self.filename


class ChatImage(models.Model):
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="images",
    )
    file = models.FileField(upload_to="chat_images/")
    filename = models.CharField(max_length=255)
    file_hash = models.CharField(max_length=64, blank=True, default="")
    content_type = models.CharField(max_length=100, blank=True, default="")
    is_active = models.BooleanField(default=False)
    activated_at = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["session", "-is_active", "-uploaded_at"], name="app_chatimg_sess_a_idx"),
            models.Index(fields=["session", "file_hash"], name="app_chatimg_sess_f_idx"),
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
    image_attachment = models.ForeignKey(
        ChatImage,
        on_delete=models.SET_NULL,
        related_name="conversations",
        null=True,
        blank=True,
    )
    image_attachments_snapshot = models.JSONField(default=list, blank=True)
    user_message = models.TextField()
    ai_message = models.TextField()
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["session", "-created_at"]),
            models.Index(fields=["session", "created_at", "id"], name="app_chatconv_hist_idx"),
        ]

    def __str__(self):
        return self.user_message[:80]


class LearningQuizSession(models.Model):
    LEVEL_BEGINNER = "beginner"
    LEVEL_INTERMEDIATE = "intermediate"
    LEVEL_ADVANCED = "advanced"
    LEVEL_MASTER = "master"
    LEVEL_ENTERPRISES_MASTERY = "enterprises mastery"
    LEVEL_CHOICES = (
        (LEVEL_BEGINNER, "Beginner"),
        (LEVEL_INTERMEDIATE, "Intermediate"),
        (LEVEL_ADVANCED, "Advanced"),
        (LEVEL_MASTER, "Master"),
        (LEVEL_ENTERPRISES_MASTERY, "Enterprises mastery"),
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="learning_quiz_sessions",
    )
    topic = models.CharField(max_length=200)
    model = models.CharField(max_length=100)
    difficulty_level = models.CharField(
        max_length=40,
        choices=LEVEL_CHOICES,
        default=LEVEL_BEGINNER,
    )
    total_questions = models.PositiveIntegerField(default=5)
    correct_answers = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["owner", "-created_at"], name="app_learnquiz_owner_idx"),
        ]

    def __str__(self):
        return f"{self.owner} - {self.topic}"


class LearningQuizQuestion(models.Model):
    quiz_session = models.ForeignKey(
        LearningQuizSession,
        on_delete=models.CASCADE,
        related_name="questions",
    )
    question_text = models.TextField()
    option_a = models.CharField(max_length=500)
    option_b = models.CharField(max_length=500)
    option_c = models.CharField(max_length=500)
    option_d = models.CharField(max_length=500)
    correct_option = models.CharField(max_length=1)
    explanation = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    selected_option = models.CharField(max_length=1, blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sort_order", "id"]
        indexes = [
            models.Index(fields=["quiz_session", "sort_order"], name="app_learnqz_sort_idx"),
        ]

    def __str__(self):
        return f"{self.quiz_session.topic} #{self.sort_order}"


class BackgroundJob(models.Model):
    KIND_LEARNING_QUIZ = "learning_quiz"
    KIND_LEARNING_PATH = "learning_path"
    KIND_DOCUMENT_INGEST = "document_ingest"
    KIND_ROAST = "roast"
    KIND_FORTUNE = "fortune"
    KIND_CHOICES = (
        (KIND_LEARNING_QUIZ, "Learning quiz"),
        (KIND_LEARNING_PATH, "Learning path"),
        (KIND_DOCUMENT_INGEST, "Document ingest"),
        (KIND_ROAST, "Roast"),
        (KIND_FORTUNE, "Fortune"),
    )

    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    )

    id = models.CharField(primary_key=True, default=generate_uuid, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="background_jobs",
    )
    kind = models.CharField(max_length=50, choices=KIND_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    title = models.CharField(max_length=255, blank=True, default="")
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.SET_NULL,
        related_name="background_jobs",
        null=True,
        blank=True,
    )
    document = models.ForeignKey(
        ChatDocument,
        on_delete=models.SET_NULL,
        related_name="background_jobs",
        null=True,
        blank=True,
    )
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["owner", "status", "-created_at"], name="app_bgjob_owner_s_idx"),
            models.Index(fields=["status", "created_at"], name="app_bgjob_status_c_idx"),
        ]

    def __str__(self):
        return f"{self.owner} - {self.kind} - {self.status}"


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
