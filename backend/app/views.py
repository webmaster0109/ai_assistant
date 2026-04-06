import json
import uuid
import hashlib
from datetime import timedelta
from functools import wraps

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.db.models import OuterRef, Prefetch, Subquery
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods

from .langchain import (
    clear_history_cache,
    clear_stream_stop,
    conversation_chain,
    conversation_chain_stream,
    generate_title,
    load_regeneration_history,
    request_stream_stop,
    set_session_history,
)
from .models import (
    BackgroundJob,
    ChatConversations,
    ChatDocument,
    ChatImage,
    ChatSession,
    LearningQuizQuestion,
    LearningQuizSession,
)
from .ollama import list_models, supports_documents, supports_vision
from .utils import cloud_usage_by_model, cloud_usage_stats, get_website_branding


User = get_user_model()
MAX_PINNED_SESSIONS = 3
ALLOWED_DOCUMENT_CONTENT_TYPES = {"application/pdf"}
MAX_DOCUMENT_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_IMAGE_UPLOAD_BYTES = 50 * 1024 * 1024


def parse_request_data(request):
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}
    return request.POST


def json_error(message, status=400):
    return JsonResponse({"detail": message}, status=status)


def sse_event(event_name, payload):
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"


def generate_share_token():
    token = uuid.uuid4().hex
    while ChatSession.objects.filter(share_token=token).exists():
        token = uuid.uuid4().hex
    return token


def build_share_path(session):
    if not session.is_public or not session.share_token:
        return ""
    return f"/share/{session.share_token}/"


def hash_uploaded_file(uploaded_file):
    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    return digest.hexdigest()


def ensure_document_file_hash(document):
    if document.file_hash:
        return document.file_hash

    digest = hashlib.sha256()
    try:
        with document.file.open("rb") as stored_file:
            for chunk in iter(lambda: stored_file.read(8192), b""):
                digest.update(chunk)
    except OSError:
        return ""
    document.file_hash = digest.hexdigest()
    document.save(update_fields=["file_hash"])
    return document.file_hash


def ensure_image_file_hash(image):
    if image.file_hash:
        return image.file_hash

    digest = hashlib.sha256()
    try:
        with image.file.open("rb") as stored_file:
            for chunk in iter(lambda: stored_file.read(8192), b""):
                digest.update(chunk)
    except OSError:
        return ""
    image.file_hash = digest.hexdigest()
    image.save(update_fields=["file_hash"])
    return image.file_hash


def deactivate_session_documents(session, *, exclude_id=None):
    queryset = session.documents.filter(is_active=True)
    if exclude_id is not None:
        queryset = queryset.exclude(id=exclude_id)
    queryset.update(is_active=False)


def deactivate_session_images(session, *, exclude_id=None, exclude_ids=None):
    queryset = session.images.filter(is_active=True)
    if exclude_id is not None:
        queryset = queryset.exclude(id=exclude_id)
    if exclude_ids:
        queryset = queryset.exclude(id__in=list(exclude_ids))
    queryset.update(is_active=False)


def login_required_json(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return json_error("Authentication required.", status=401)
        return view_func(request, *args, **kwargs)

    return wrapped


def fallback_title(message):
    words = " ".join(message.strip().split())
    if not words:
        return "New chat"
    shortened = words[:60].strip()
    return shortened if len(words) <= 60 else f"{shortened}..."


def build_title(message):
    try:
        title = generate_title(message).strip()
    except Exception:
        title = ""
    return title or fallback_title(message)


def serialize_user(user):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
    }


def serialize_document(document):
    return {
        "id": document.id,
        "name": document.filename,
        "uploaded_at": document.uploaded_at.isoformat(),
        "extracted_characters": document.extracted_characters,
        "is_active": document.is_active,
        "processing_status": document.processing_status,
        "processing_error": document.processing_error,
        "is_ready": document.processing_status == ChatDocument.STATUS_READY,
    }


def serialize_image(image):
    return {
        "id": image.id,
        "name": image.filename,
        "uploaded_at": image.uploaded_at.isoformat(),
        "is_active": image.is_active,
        "content_type": image.content_type,
        "url": image.file.url if image.file else "",
    }


def serialize_image_list(images):
    return [serialize_image(image) for image in images]


def serialize_session(session):
    latest_preview = getattr(session, "latest_user_message", None)
    if latest_preview is None:
        latest_conversation = session.conversations.order_by("-created_at", "-id").first()
        latest_preview = latest_conversation.user_message[:120] if latest_conversation else ""
    documents = session.get_documents()
    active_document = session.get_active_document()
    images = session.get_images()
    active_images = session.get_active_images()
    active_image = active_images[0] if active_images else None
    return {
        "id": session.id,
        "title": session.title,
        "model": session.model,
        "is_pinned": session.is_pinned,
        "is_public": session.is_public,
        "share_url": build_share_path(session),
        "document": serialize_document(active_document) if active_document else None,
        "documents": [serialize_document(document) for document in documents],
        "image": serialize_image(active_image) if active_image else None,
        "active_images": serialize_image_list(active_images),
        "images": [serialize_image(image) for image in images],
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "preview": latest_preview or "",
    }


def serialize_message(message):
    image_attachments = message.image_attachments_snapshot or []
    if not image_attachments and message.image_attachment:
        image_attachments = [serialize_image(message.image_attachment)]
    return {
        "id": message.id,
        "session_id": message.session_id,
        "image_attachment": serialize_image(message.image_attachment) if message.image_attachment else None,
        "image_attachments": image_attachments,
        "user_message": message.user_message,
        "ai_message": message.ai_message,
        "input_tokens": message.input_tokens,
        "output_tokens": message.output_tokens,
        "created_at": message.created_at.isoformat(),
    }


def snapshot_images(images):
    return [serialize_image(image) for image in images]


def resolve_conversation_image_attachments(conversation):
    snapshot = conversation.image_attachments_snapshot or []
    snapshot_ids = [item.get("id") for item in snapshot if item.get("id")]
    attachments = []
    if snapshot_ids:
        image_map = {
            image.id: image
            for image in conversation.session.images.filter(id__in=snapshot_ids)
        }
        attachments = [image_map[item_id] for item_id in snapshot_ids if item_id in image_map]
    elif conversation.image_attachment_id:
        attachments = [conversation.image_attachment]
    return attachments


def serialize_learning_quiz_question(question):
    revealed = bool(question.selected_option)
    return {
        "id": question.id,
        "sort_order": question.sort_order,
        "question_text": question.question_text,
        "options": {
            "A": question.option_a,
            "B": question.option_b,
            "C": question.option_c,
            "D": question.option_d,
        },
        "selected_option": question.selected_option or "",
        "is_correct": question.is_correct,
        "correct_option": question.correct_option if revealed else "",
        "explanation": question.explanation if revealed else "",
    }


def serialize_learning_quiz_session(quiz, include_questions=False):
    questions = list(getattr(quiz, "_prefetched_objects_cache", {}).get("questions", []))
    if not questions and include_questions:
        questions = list(quiz.questions.all())

    answered_questions = (
        sum(1 for item in questions if item.selected_option)
        if questions
        else quiz.questions.exclude(selected_option="").count()
    )
    total_questions = quiz.total_questions or len(questions)
    score_percent = round((quiz.correct_answers / total_questions) * 100) if total_questions else 0

    payload = {
        "id": quiz.id,
        "topic": quiz.topic,
        "model": quiz.model,
        "difficulty_level": quiz.difficulty_level,
        "difficulty_label": quiz.get_difficulty_level_display(),
        "total_questions": total_questions,
        "answered_questions": answered_questions,
        "correct_answers": quiz.correct_answers,
        "score_percent": score_percent,
        "is_completed": bool(quiz.completed_at),
        "created_at": quiz.created_at.isoformat(),
        "completed_at": quiz.completed_at.isoformat() if quiz.completed_at else None,
    }
    if include_questions:
        payload["questions"] = [serialize_learning_quiz_question(question) for question in questions]
    return payload


def serialize_background_job(job):
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "title": job.title,
        "session_id": job.session_id,
        "document_id": job.document_id,
        "payload": job.payload or {},
        "result": job.result or {},
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def enqueue_background_job(*, owner, kind, title="", session=None, document=None, payload=None):
    return BackgroundJob.objects.create(
        owner=owner,
        kind=kind,
        title=title,
        session=session,
        document=document,
        payload=payload or {},
    )


def get_owned_session_or_404(request, session_id):
    return ChatSession.objects.filter(owner=request.user, id=session_id).first()


def get_public_session_or_404(share_token):
    return ChatSession.objects.filter(is_public=True, share_token=share_token).first()


def ordered_sessions_for_user(user):
    latest_conversation = (
        ChatConversations.objects.filter(session_id=OuterRef("pk"))
        .order_by("-created_at", "-id")
    )
    return (
        ChatSession.objects.filter(owner=user)
        .annotate(
            latest_user_message=Subquery(latest_conversation.values("user_message")[:1]),
        )
        .prefetch_related(
            Prefetch(
                "documents",
                queryset=ChatDocument.objects.order_by("-is_active", "-uploaded_at"),
            ),
            Prefetch(
                "images",
                queryset=ChatImage.objects.order_by("-is_active", "activated_at", "-uploaded_at"),
            ),
        )
        .order_by("-is_pinned", "-updated_at")
    )


@ensure_csrf_cookie
@require_GET
def app_shell(request, share_token=None):
    branding = get_website_branding()
    return render(
        request,
        "app.html",
        {
            "website_name": branding.get("website_name") or "Ollama AI",
            "website_description": branding.get("website_description") or "Private AI chat workspace",
            "website_favicon": branding.get("website_favicon") or "",
        },
    )


@require_GET
def favicon(request):
    branding = get_website_branding()
    favicon_url = branding.get("website_favicon") or static("frontend/pwa-icon-192.png")
    return HttpResponseRedirect(favicon_url)


@require_GET
def service_worker(request):
    content = render_to_string("sw.js")
    return HttpResponse(content, content_type="application/javascript")


@require_GET
def web_manifest(request):
    branding = get_website_branding()
    icons = [
        {
            "src": static("frontend/pwa-icon-192.png"),
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "any",
        },
        {
            "src": static("frontend/pwa-icon-512.png"),
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any maskable",
        },
    ]

    return JsonResponse(
        {
            "name": branding.get("website_name") or "Ollama AI",
            "short_name": branding.get("website_name") or "Ollama AI",
            "description": branding.get("website_description") or "Private AI chat workspace",
            "id": "/",
            "start_url": "/",
            "scope": "/",
            "display_override": ["standalone", "minimal-ui", "browser"],
            "display": "standalone",
            "background_color": "#0c1116",
            "theme_color": "#17594a",
            "prefer_related_applications": False,
            "icons": icons,
        },
        content_type="application/manifest+json",
    )


@ensure_csrf_cookie
@require_GET
def auth_status(request):
    branding = get_website_branding()
    return JsonResponse(
        {
            "authenticated": request.user.is_authenticated,
            "user": serialize_user(request.user) if request.user.is_authenticated else None,
            "branding": branding,
        },
        status=200,
    )


@require_http_methods(["POST"])
def register_user(request):
    payload = parse_request_data(request)
    username = (payload.get("username") or "").strip()
    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""
    password_confirm = payload.get("password_confirm") or ""

    if not username or not email or not password:
        return json_error("Username, email, and password are required.")
    if password != password_confirm:
        return json_error("Passwords do not match.")
    if User.objects.filter(username__iexact=username).exists():
        return json_error("That username is already in use.")
    if User.objects.filter(email__iexact=email).exists():
        return json_error("That email is already in use.")

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
    )
    login(request, user)
    return JsonResponse({"user": serialize_user(user)}, status=201)


@require_http_methods(["POST"])
def login_user(request):
    payload = parse_request_data(request)
    identifier = (payload.get("identifier") or payload.get("username") or "").strip()
    password = payload.get("password") or ""

    if not identifier or not password:
        return json_error("Username or email and password are required.")

    username = identifier
    if "@" in identifier:
        matched_user = User.objects.filter(email__iexact=identifier).first()
        if matched_user:
            username = matched_user.username

    user = authenticate(request, username=username, password=password)
    if user is None:
        return json_error("Invalid credentials.", status=401)

    login(request, user)
    return JsonResponse({"user": serialize_user(user)}, status=200)


@require_http_methods(["POST"])
def logout_user(request):
    logout(request)
    return JsonResponse({"success": True}, status=200)


@require_GET
def models_catalog(request):
    return JsonResponse({"models": list_models()}, status=200)


@login_required_json
@require_GET
def background_job_list(request):
    jobs = BackgroundJob.objects.filter(
        owner=request.user,
        status__in=[BackgroundJob.STATUS_QUEUED, BackgroundJob.STATUS_RUNNING],
    ).order_by("-created_at")[:20]
    return JsonResponse({"jobs": [serialize_background_job(job) for job in jobs]}, status=200)


@login_required_json
@require_GET
def background_job_detail(request, job_id):
    job = BackgroundJob.objects.filter(owner=request.user, id=job_id).first()
    if job is None:
        return json_error("Background job not found.", status=404)
    return JsonResponse({"job": serialize_background_job(job)}, status=200)


@login_required_json
@require_GET
def learning_quiz_sessions(request):
    quizzes = (
        LearningQuizSession.objects.filter(owner=request.user)
        .prefetch_related("questions")
        .order_by("-created_at")[:12]
    )
    return JsonResponse(
        {"quizzes": [serialize_learning_quiz_session(quiz, include_questions=True) for quiz in quizzes]},
        status=200,
    )


@login_required_json
@require_GET
def learning_quiz_detail(request, quiz_id):
    quiz = (
        LearningQuizSession.objects.filter(owner=request.user, id=quiz_id)
        .prefetch_related("questions")
        .first()
    )
    if quiz is None:
        return json_error("Quiz not found.", status=404)

    return JsonResponse(
        {"quiz": serialize_learning_quiz_session(quiz, include_questions=True)},
        status=200,
    )


@login_required_json
@require_http_methods(["DELETE"])
def delete_learning_quiz(request, quiz_id):
    quiz = LearningQuizSession.objects.filter(owner=request.user, id=quiz_id).first()
    if quiz is None:
        return json_error("Quiz not found.", status=404)

    quiz.delete()
    return JsonResponse({"success": True, "quiz_id": quiz_id}, status=200)


@login_required_json
@require_http_methods(["POST"])
def create_learning_quiz(request):
    payload = parse_request_data(request)
    topic = (payload.get("topic") or "").strip()
    difficulty_level = (payload.get("difficulty_level") or LearningQuizSession.LEVEL_BEGINNER).strip().lower()
    question_count = payload.get("question_count") or 5

    try:
        question_count = int(question_count)
    except (TypeError, ValueError):
        return json_error("Question count must be a number.")

    question_count = max(3, min(question_count, 10))

    if not topic:
        return json_error("Quiz topic is required.")

    if difficulty_level not in {item[0] for item in LearningQuizSession.LEVEL_CHOICES}:
        return json_error("Please choose a valid quiz level.")

    model = "gemma4"
    available_keys = {item["key"] for item in list_models()}
    if model not in available_keys:
        return json_error("Gemma 4 quiz generation is unavailable right now.")

    job = enqueue_background_job(
        owner=request.user,
        kind=BackgroundJob.KIND_LEARNING_QUIZ,
        title=f"Quiz: {topic}",
        payload={
            "topic": topic,
            "model": model,
            "difficulty_level": difficulty_level,
            "question_count": question_count,
        },
    )
    return JsonResponse({"job": serialize_background_job(job)}, status=202)


@login_required_json
@require_http_methods(["POST"])
def answer_learning_quiz_question(request, quiz_id, question_id):
    quiz = (
        LearningQuizSession.objects.filter(owner=request.user, id=quiz_id)
        .prefetch_related("questions")
        .first()
    )
    if quiz is None:
        return json_error("Quiz not found.", status=404)

    question = next((item for item in quiz.questions.all() if item.id == question_id), None)
    if question is None:
        return json_error("Quiz question not found.", status=404)
    if quiz.completed_at:
        return json_error("This quiz is already completed.")
    if question.selected_option:
        return json_error("This question has already been answered.")

    payload = parse_request_data(request)
    selected_option = (payload.get("selected_option") or "").strip().upper()
    if selected_option not in {"A", "B", "C", "D"}:
        return json_error("Please choose a valid option.")

    question.selected_option = selected_option
    question.is_correct = selected_option == question.correct_option
    question.answered_at = timezone.now()
    question.save(update_fields=["selected_option", "is_correct", "answered_at"])

    answered_questions = 0
    correct_answers = 0
    for item in quiz.questions.all():
        if item.id == question.id:
            current = question
        else:
            current = item
        if current.selected_option:
            answered_questions += 1
        if current.is_correct:
            correct_answers += 1

    quiz.correct_answers = correct_answers
    if answered_questions >= quiz.total_questions:
        quiz.completed_at = timezone.now()
        quiz.save(update_fields=["correct_answers", "completed_at", "updated_at"])
    else:
        quiz.save(update_fields=["correct_answers", "updated_at"])

    quiz = LearningQuizSession.objects.prefetch_related("questions").get(id=quiz.id)
    return JsonResponse(
        {
            "quiz": serialize_learning_quiz_session(quiz, include_questions=True),
            "question": serialize_learning_quiz_question(
                next(item for item in quiz.questions.all() if item.id == question.id)
            ),
        },
        status=200,
    )


@login_required_json
@require_http_methods(["POST"])
def create_learning_path(request):
    payload = parse_request_data(request)
    goal = (payload.get("goal") or "").strip()
    model = (payload.get("model") or "").strip()
    experience_level = (payload.get("experience_level") or LearningQuizSession.LEVEL_BEGINNER).strip().lower()
    weekly_hours = (payload.get("weekly_hours") or "").strip()
    timeline = (payload.get("timeline") or "").strip()

    if not goal:
        return json_error("Learning goal is required.")

    available_keys = {item["key"] for item in list_models()}
    if model not in available_keys:
        return json_error("Please choose a valid model.")
    if experience_level not in {item[0] for item in LearningQuizSession.LEVEL_CHOICES}:
        return json_error("Please choose a valid learning level.")

    job = enqueue_background_job(
        owner=request.user,
        kind=BackgroundJob.KIND_LEARNING_PATH,
        title=f"Roadmap: {goal}",
        payload={
            "goal": goal,
            "model": model,
            "experience_level": experience_level,
            "weekly_hours": weekly_hours,
            "timeline": timeline,
        },
    )
    return JsonResponse({"job": serialize_background_job(job)}, status=202)


@login_required_json
@require_http_methods(["POST"])
def create_roast(request):
    payload = parse_request_data(request)
    content = (payload.get("content") or "").strip()
    content_type = (payload.get("content_type") or "auto").strip().lower()
    language = (payload.get("language") or "english").strip().lower()
    improvement_goal = (payload.get("improvement_goal") or "").strip()

    if not content:
        return json_error("Something to roast is required.")

    if content_type not in {"auto", "code", "writing", "message"}:
        return json_error("Please choose a valid roast type.")
    if language not in {"english", "hindi", "nepali"}:
        return json_error("Please choose a valid roast language.")

    model = "qwen3.5"
    available_keys = {item["key"] for item in list_models()}
    if model not in available_keys:
        return json_error("Roast mode is unavailable right now.")

    title_seed = content.splitlines()[0][:60].strip() or "Untitled roast"
    job = enqueue_background_job(
        owner=request.user,
        kind=BackgroundJob.KIND_ROAST,
        title=f"Roast: {title_seed}",
        payload={
            "content": content,
            "content_type": content_type,
            "language": language,
            "improvement_goal": improvement_goal,
            "model": model,
        },
    )
    return JsonResponse({"job": serialize_background_job(job)}, status=202)


@login_required_json
@require_http_methods(["POST"])
def create_fortune(request):
    payload = parse_request_data(request)
    question = (payload.get("question") or "").strip()
    focus_area = (payload.get("focus_area") or "general").strip().lower()
    language = (payload.get("language") or "english").strip().lower()

    if not question:
        return json_error("A question for the fortune teller is required.")
    if focus_area not in {"general", "love", "career", "money", "study", "friendship"}:
        return json_error("Please choose a valid fortune focus area.")
    if language not in {"english", "hindi", "nepali"}:
        return json_error("Please choose a valid fortune language.")

    model = "deepseek-v3.1"
    available_keys = {item["key"] for item in list_models()}
    if model not in available_keys:
        return json_error("Fortune Teller Mode is unavailable right now.")

    title_seed = question.splitlines()[0][:60].strip() or "Untitled reading"
    job = enqueue_background_job(
        owner=request.user,
        kind=BackgroundJob.KIND_FORTUNE,
        title=f"Fortune: {title_seed}",
        payload={
            "question": question,
            "focus_area": focus_area,
            "language": language,
            "model": model,
        },
    )
    return JsonResponse({"job": serialize_background_job(job)}, status=202)


@login_required_json
@require_GET
def chat_sessions(request):
    sessions = ordered_sessions_for_user(request.user)
    return JsonResponse({"sessions": [serialize_session(session) for session in sessions]}, status=200)


@login_required_json
@require_GET
def chat_history_conversations(request, session_id):
    session = get_owned_session_or_404(request, session_id)
    if session is None:
        return json_error("Session not found.", status=404)

    conversations = session.conversations.select_related("image_attachment").order_by("created_at", "id")
    return JsonResponse(
        {
            "session": serialize_session(session),
            "messages": [serialize_message(conversation) for conversation in conversations],
        },
        status=200,
    )


@login_required_json
@require_http_methods(["POST"])
def upload_chat_document(request):
    uploaded_file = request.FILES.get("file")
    session_id = (request.POST.get("session_id") or "").strip()
    requested_model = (request.POST.get("model") or "").strip()

    if uploaded_file is None:
        return json_error("Please choose a PDF file to upload.")

    if uploaded_file.content_type not in ALLOWED_DOCUMENT_CONTENT_TYPES:
        return json_error("Only PDF files are supported right now. Image chat needs OCR setup first.")

    if uploaded_file.size > MAX_DOCUMENT_UPLOAD_BYTES:
        return json_error("PDF size must be 100 MB or less.")

    if session_id:
        session = get_owned_session_or_404(request, session_id)
        if session is None:
            return json_error("Session not found.", status=404)
        model_key = session.model
    else:
        model_key = requested_model
        if not model_key:
            return json_error("Please choose a document-capable model first.")
        available_keys = {item["key"] for item in list_models()}
        if model_key not in available_keys:
            return json_error("Please choose a valid model.")
        session = None

    if not supports_documents(model_key):
        return json_error("This model does not support document chat. Choose one of the unlocked document models.")

    if session is None:
        session = ChatSession.objects.create(
            owner=request.user,
            model=model_key,
            title=fallback_title(uploaded_file.name.rsplit(".", 1)[0]),
        )

    uploaded_file_hash = hash_uploaded_file(uploaded_file)
    existing_documents = list(session.documents.all())
    duplicate_document = next(
        (
            document
            for document in existing_documents
            if ensure_document_file_hash(document) == uploaded_file_hash
        ),
        None,
    )
    if duplicate_document is not None:
        deactivate_session_documents(session, exclude_id=duplicate_document.id)
        deactivate_session_images(session)
        if not duplicate_document.is_active:
            duplicate_document.is_active = True
            duplicate_document.save(update_fields=["is_active"])

        clear_history_cache(session.id)
        session.updated_at = timezone.now()
        session.save(update_fields=["updated_at"])

        session = ordered_sessions_for_user(request.user).filter(id=session.id).first() or session
        return JsonResponse(
            {
                "session": serialize_session(session),
                "document": serialize_document(duplicate_document),
                "reused": True,
            },
            status=200,
        )

    document = ChatDocument.objects.create(
        session=session,
        file=uploaded_file,
        filename=uploaded_file.name,
        file_hash=uploaded_file_hash,
        is_active=True,
        processing_status=ChatDocument.STATUS_QUEUED,
        processing_error="",
    )
    deactivate_session_documents(session, exclude_id=document.id)
    deactivate_session_images(session)

    clear_history_cache(session.id)
    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])

    job = enqueue_background_job(
        owner=request.user,
        kind=BackgroundJob.KIND_DOCUMENT_INGEST,
        title=f"PDF: {document.filename}",
        session=session,
        document=document,
        payload={
            "session_id": session.id,
            "document_id": document.id,
            "filename": document.filename,
        },
    )

    return JsonResponse(
        {
            "session": serialize_session(session),
            "document": serialize_document(document),
            "job": serialize_background_job(job),
        },
        status=202,
    )


@login_required_json
@require_http_methods(["POST"])
def upload_chat_image(request):
    uploaded_files = request.FILES.getlist("files") or []
    if not uploaded_files:
        single_file = request.FILES.get("file")
        if single_file is not None:
            uploaded_files = [single_file]
    session_id = (request.POST.get("session_id") or "").strip()
    requested_model = (request.POST.get("model") or "").strip()

    if not uploaded_files:
        return json_error("Please choose at least one image to upload.")

    total_upload_bytes = sum(item.size for item in uploaded_files)
    if total_upload_bytes > MAX_IMAGE_UPLOAD_BYTES:
        return json_error("Selected images must be 50 MB or less in total.")

    for uploaded_file in uploaded_files:
        content_type = uploaded_file.content_type or ""
        if not content_type.startswith("image/"):
            return json_error("Only image files are supported for vision chat.")

    if session_id:
        session = get_owned_session_or_404(request, session_id)
        if session is None:
            return json_error("Session not found.", status=404)
        model_key = session.model
    else:
        model_key = requested_model
        if not model_key:
            return json_error("Please choose a vision-capable model first.")
        available_keys = {item["key"] for item in list_models()}
        if model_key not in available_keys:
            return json_error("Please choose a valid model.")
        session = None

    if not supports_vision(model_key):
        return json_error("This model does not support image chat. Choose one of the unlocked vision models.")

    if session is None:
        session = ChatSession.objects.create(
            owner=request.user,
            model=model_key,
            title=fallback_title(uploaded_files[0].name.rsplit(".", 1)[0]),
        )

    existing_images = list(session.images.all())
    selected_images = []
    reused_count = 0

    for uploaded_file in uploaded_files:
        uploaded_file_hash = hash_uploaded_file(uploaded_file)
        duplicate_image = next(
            (
                image
                for image in existing_images
                if ensure_image_file_hash(image) == uploaded_file_hash
            ),
            None,
        )
        if duplicate_image is not None:
            reused_count += 1
            if not duplicate_image.is_active:
                duplicate_image.is_active = True
                duplicate_image.save(update_fields=["is_active"])
            selected_images.append(duplicate_image)
            continue

        content_type = uploaded_file.content_type or ""
        image = ChatImage.objects.create(
            session=session,
            file=uploaded_file,
            filename=uploaded_file.name,
            file_hash=uploaded_file_hash,
            content_type=content_type,
            is_active=True,
        )
        existing_images.append(image)
        selected_images.append(image)

    active_ids = {image.id for image in session.get_active_images()}
    active_ids.update(image.id for image in selected_images)
    deactivate_session_images(session, exclude_ids=active_ids)
    deactivate_session_documents(session)

    activation_base = timezone.now()
    for offset, image in enumerate(selected_images):
        image.is_active = True
        image.activated_at = activation_base + timedelta(microseconds=offset)
        image.save(update_fields=["is_active", "activated_at"])

    clear_history_cache(session.id)
    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])

    session = ordered_sessions_for_user(request.user).filter(id=session.id).first() or session

    return JsonResponse(
        {
            "session": serialize_session(session),
            "images": serialize_image_list(selected_images),
            "image": serialize_image(selected_images[0]) if selected_images else None,
            "reused_count": reused_count,
        },
        status=200 if reused_count == len(selected_images) else 201,
    )


@login_required_json
@require_http_methods(["POST"])
def select_chat_image(request, session_id, image_id):
    session = get_owned_session_or_404(request, session_id)
    if session is None:
        return json_error("Session not found.", status=404)

    image = session.images.filter(id=image_id).first()
    if image is None:
        return json_error("Image not found.", status=404)

    deactivate_session_documents(session)
    if not image.is_active:
        image.is_active = True
    image.activated_at = timezone.now()
    image.save(update_fields=["is_active", "activated_at"])

    clear_history_cache(session.id)
    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])

    session = ordered_sessions_for_user(request.user).filter(id=session.id).first() or session
    return JsonResponse(
        {
            "session": serialize_session(session),
            "image": serialize_image(image),
        },
        status=200,
    )


@login_required_json
@require_http_methods(["POST"])
def select_chat_document(request, session_id, document_id):
    session = get_owned_session_or_404(request, session_id)
    if session is None:
        return json_error("Session not found.", status=404)

    document = session.documents.filter(id=document_id).first()
    if document is None:
        return json_error("Document not found.", status=404)

    deactivate_session_documents(session, exclude_id=document.id)
    deactivate_session_images(session)
    if not document.is_active:
        document.is_active = True
        document.save(update_fields=["is_active"])

    clear_history_cache(session.id)
    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])

    session = ordered_sessions_for_user(request.user).filter(id=session.id).first() or session
    return JsonResponse(
        {
            "session": serialize_session(session),
            "document": serialize_document(document),
        },
        status=200,
    )


@login_required_json
@require_http_methods(["POST"])
def deactivate_chat_image(request, session_id, image_id):
    session = get_owned_session_or_404(request, session_id)
    if session is None:
        return json_error("Session not found.", status=404)

    image = session.images.filter(id=image_id).first()
    if image is None:
        return json_error("Image not found.", status=404)

    if image.is_active:
        image.is_active = False
        image.activated_at = None
        image.save(update_fields=["is_active", "activated_at"])

    clear_history_cache(session.id)
    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])

    session = ordered_sessions_for_user(request.user).filter(id=session.id).first() or session
    return JsonResponse(
        {
            "session": serialize_session(session),
            "image": serialize_image(image),
        },
        status=200,
    )


@login_required_json
@require_http_methods(["POST"])
def deactivate_all_chat_images(request, session_id):
    session = get_owned_session_or_404(request, session_id)
    if session is None:
        return json_error("Session not found.", status=404)

    session.images.filter(is_active=True).update(is_active=False, activated_at=None)

    clear_history_cache(session.id)
    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])

    session = ordered_sessions_for_user(request.user).filter(id=session.id).first() or session
    return JsonResponse(
        {
            "session": serialize_session(session),
            "success": True,
        },
        status=200,
    )


@login_required_json
@require_http_methods(["POST"])
def deactivate_chat_document(request, session_id, document_id):
    session = get_owned_session_or_404(request, session_id)
    if session is None:
        return json_error("Session not found.", status=404)

    document = session.documents.filter(id=document_id).first()
    if document is None:
        return json_error("Document not found.", status=404)

    if document.is_active:
        document.is_active = False
        document.save(update_fields=["is_active"])

    clear_history_cache(session.id)
    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])

    session = ordered_sessions_for_user(request.user).filter(id=session.id).first() or session
    return JsonResponse(
        {
            "session": serialize_session(session),
            "document": serialize_document(document),
        },
        status=200,
    )


@login_required_json
@require_http_methods(["DELETE"])
def delete_chat_image(request, session_id, image_id):
    session = get_owned_session_or_404(request, session_id)
    if session is None:
        return json_error("Session not found.", status=404)

    image = session.images.filter(id=image_id).first()
    if image is None:
        return json_error("Image not found.", status=404)

    image.file.delete(save=False)
    image.delete()

    clear_history_cache(session.id)
    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])

    session = ordered_sessions_for_user(request.user).filter(id=session.id).first() or session
    return JsonResponse({"session": serialize_session(session), "success": True}, status=200)


@login_required_json
@require_http_methods(["DELETE"])
def delete_chat_document(request, session_id, document_id):
    session = get_owned_session_or_404(request, session_id)
    if session is None:
        return json_error("Session not found.", status=404)

    document = session.documents.filter(id=document_id).first()
    if document is None:
        return json_error("Document not found.", status=404)

    was_active = document.is_active
    document.file.delete(save=False)
    document.delete()

    if was_active:
        next_document = session.documents.order_by("-uploaded_at").first()
        if next_document is not None and not next_document.is_active:
            next_document.is_active = True
            next_document.save(update_fields=["is_active"])

    clear_history_cache(session.id)
    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])

    session = ordered_sessions_for_user(request.user).filter(id=session.id).first() or session
    return JsonResponse({"session": serialize_session(session), "success": True}, status=200)


@login_required_json
@require_http_methods(["POST"])
def chat_post(request):
    payload = parse_request_data(request)
    message = (payload.get("message") or "").strip()
    model = (payload.get("model") or "").strip()
    session_id = (payload.get("session_id") or "").strip()

    if not message:
        return json_error("Message is required.")

    if session_id:
        session = get_owned_session_or_404(request, session_id)
        if session is None:
            return json_error("Session not found.", status=404)
        model = session.model
    else:
        available_keys = {item["key"] for item in list_models()}
        if model not in available_keys:
            return json_error("Please choose a valid model.")
        session = ChatSession.objects.create(
            owner=request.user,
            model=model,
            title=build_title(message),
        )

    active_images = session.get_active_images()
    if active_images and not supports_vision(session.model):
        return json_error("This chat's model does not support image questions. Start a vision-capable chat first.")
    active_document = session.get_active_document()
    if active_document and active_document.processing_status != ChatDocument.STATUS_READY:
        if active_document.processing_status == ChatDocument.STATUS_FAILED:
            detail = active_document.processing_error or "The selected PDF could not be processed."
            return json_error(detail)
        return json_error("The selected PDF is still processing in the background. Please wait a moment and try again.")

    response, usage = conversation_chain(
        model,
        message,
        session_id=session.id,
        image_attachments=active_images or None,
    )
    conversation = ChatConversations.objects.create(
        session=session,
        image_attachment=active_images[0] if active_images else None,
        image_attachments_snapshot=snapshot_images(active_images),
        user_message=message,
        ai_message=response,
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
    )
    set_session_history(session.id, message, response)

    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])

    return JsonResponse(
        {
            "session": serialize_session(session),
            "message": serialize_message(conversation),
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
        },
        status=200,
    )


@login_required_json
@require_http_methods(["POST"])
def chat_stream(request):
    payload = parse_request_data(request)
    message = (payload.get("message") or "").strip()
    model = (payload.get("model") or "").strip()
    session_id = (payload.get("session_id") or "").strip()

    if not message:
        return json_error("Message is required.")

    created_new_session = False
    if session_id:
        session = get_owned_session_or_404(request, session_id)
        if session is None:
            return json_error("Session not found.", status=404)
        model = session.model
    else:
        available_keys = {item["key"] for item in list_models()}
        if model not in available_keys:
            return json_error("Please choose a valid model.")
        session = ChatSession.objects.create(
            owner=request.user,
            model=model,
            # Avoid a second blocking model call before streaming starts.
            title=fallback_title(message),
        )
        created_new_session = True

    active_images = session.get_active_images()
    if active_images and not supports_vision(session.model):
        return json_error("This chat's model does not support image questions. Start a vision-capable chat first.")
    active_document = session.get_active_document()
    if active_document and active_document.processing_status != ChatDocument.STATUS_READY:
        if active_document.processing_status == ChatDocument.STATUS_FAILED:
            detail = active_document.processing_error or "The selected PDF could not be processed."
            return json_error(detail)
        return json_error("The selected PDF is still processing in the background. Please wait a moment and try again.")

    stream_id = uuid.uuid4().hex

    def event_stream():
        final_payload = {
            "content": "",
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "stopped": False,
        }

        try:
            yield sse_event("init", {
                "stream_id": stream_id,
                "session": serialize_session(session),
            })

            for event in conversation_chain_stream(
                session.model,
                message,
                session_id=session.id,
                stream_id=stream_id,
                image_attachments=active_images or None,
            ):
                if event["type"] == "chunk":
                    yield sse_event("chunk", {"content": event["content"]})
                    continue
                final_payload = event
        except Exception as error:
            clear_stream_stop(stream_id)
            yield sse_event("error", {"detail": str(error) or "Streaming failed."})
            return

        response_text = final_payload["content"].strip()
        usage = final_payload["usage"]
        stopped = final_payload["stopped"]

        if response_text:
            conversation = ChatConversations.objects.create(
                session=session,
                image_attachment=active_images[0] if active_images else None,
                image_attachments_snapshot=snapshot_images(active_images),
                user_message=message,
                ai_message=final_payload["content"],
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )
            set_session_history(session.id, message, final_payload["content"])
            session.updated_at = timezone.now()
            session.save(update_fields=["updated_at"])

            yield sse_event(
                "done",
                {
                    "stopped": stopped,
                    "session": serialize_session(session),
                    "message": serialize_message(conversation),
                    "usage": {
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                    },
                },
            )
            return

        if created_new_session and not session.conversations.exists():
            session.delete()

        yield sse_event(
            "done",
            {
                "stopped": stopped,
                "session": None if created_new_session else serialize_session(session),
                "message": None,
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
            },
        )

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required_json
@require_http_methods(["POST"])
def regenerate_message(request, session_id, conversation_id):
    session = get_owned_session_or_404(request, session_id)
    if session is None:
        return json_error("Session not found.", status=404)

    conversation = session.conversations.filter(id=conversation_id).first()
    if conversation is None:
        return json_error("Message not found.", status=404)

    history = load_regeneration_history(session.id, conversation.id)
    response, usage = conversation_chain(
        session.model,
        conversation.user_message,
        session_id=session.id,
        history=history,
        image_attachments=resolve_conversation_image_attachments(conversation),
    )

    conversation.ai_message = response
    conversation.input_tokens = usage.get("input_tokens", 0)
    conversation.output_tokens = usage.get("output_tokens", 0)
    conversation.save(update_fields=["ai_message", "input_tokens", "output_tokens", "updated_at"])

    set_session_history(
        session.id,
        conversation.user_message,
        response,
        exclude_conversation_id=conversation.id,
    )

    session.updated_at = timezone.now()
    session.save(update_fields=["updated_at"])

    return JsonResponse(
        {
            "session": serialize_session(session),
            "message": serialize_message(conversation),
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
        },
        status=200,
    )


@login_required_json
@require_http_methods(["POST"])
def edit_message(request, session_id, conversation_id):
    session = get_owned_session_or_404(request, session_id)
    if session is None:
        return json_error("Session not found.", status=404)

    conversation = session.conversations.filter(id=conversation_id).first()
    if conversation is None:
        return json_error("Message not found.", status=404)

    payload = parse_request_data(request)
    updated_message = (payload.get("message") or "").strip()
    if not updated_message:
        return json_error("Message is required.")

    ordered_conversations = list(session.conversations.order_by("created_at", "id"))
    target_index = next(
        (index for index, item in enumerate(ordered_conversations) if item.id == conversation.id),
        None,
    )
    if target_index is None:
        return json_error("Message not found.", status=404)

    later_ids = [item.id for item in ordered_conversations[target_index + 1:]]
    if later_ids:
        ChatConversations.objects.filter(id__in=later_ids).delete()

    history = load_regeneration_history(session.id, conversation.id)
    response, usage = conversation_chain(
        session.model,
        updated_message,
        session_id=session.id,
        history=history,
        image_attachments=resolve_conversation_image_attachments(conversation),
    )

    conversation.user_message = updated_message
    conversation.ai_message = response
    conversation.input_tokens = usage.get("input_tokens", 0)
    conversation.output_tokens = usage.get("output_tokens", 0)
    conversation.save(
        update_fields=["user_message", "ai_message", "input_tokens", "output_tokens", "updated_at"]
    )

    if target_index == 0:
        session.title = fallback_title(updated_message)

    clear_history_cache(session.id)
    set_session_history(
        session.id,
        updated_message,
        response,
        exclude_conversation_id=conversation.id,
    )

    session.updated_at = timezone.now()
    save_fields = ["updated_at"]
    if target_index == 0:
        save_fields.append("title")
    session.save(update_fields=save_fields)

    return JsonResponse(
        {
            "session": serialize_session(session),
            "message": serialize_message(conversation),
            "messages": [
                serialize_message(item)
                for item in session.conversations.select_related("image_attachment").order_by("created_at", "id")
            ],
            "removed_count": len(later_ids),
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
        },
        status=200,
    )


@login_required_json
@require_http_methods(["POST"])
def toggle_session_pin(request, session_id):
    session = get_owned_session_or_404(request, session_id)
    if session is None:
        return json_error("Session not found.", status=404)

    payload = parse_request_data(request)
    pinned = payload.get("pinned")
    next_pinned_state = (not session.is_pinned) if pinned is None else bool(pinned)

    if next_pinned_state and not session.is_pinned:
        pinned_count = ChatSession.objects.filter(owner=request.user, is_pinned=True).count()
        if pinned_count >= MAX_PINNED_SESSIONS:
            return json_error("You can pin only 3 chats at a time.")

    session.is_pinned = next_pinned_state
    session.save(update_fields=["is_pinned"])
    return JsonResponse({"session": serialize_session(session)}, status=200)


@login_required_json
@require_http_methods(["POST"])
def toggle_session_visibility(request, session_id):
    session = get_owned_session_or_404(request, session_id)
    if session is None:
        return json_error("Session not found.", status=404)

    payload = parse_request_data(request)
    make_public = payload.get("is_public")
    next_public_state = (not session.is_public) if make_public is None else bool(make_public)

    if next_public_state and not session.share_token:
        session.share_token = generate_share_token()

    session.is_public = next_public_state
    session.save(update_fields=["is_public", "share_token"])
    return JsonResponse({"session": serialize_session(session)}, status=200)


@login_required_json
@require_http_methods(["POST"])
def stop_chat_stream(request, stream_id):
    request_stream_stop(stream_id)
    return JsonResponse({"success": True}, status=200)


@require_GET
def public_chat_history(request, share_token):
    session = get_public_session_or_404(share_token)
    if session is None:
        return json_error("Shared chat not found.", status=404)

    return JsonResponse(
        {
            "session": serialize_session(session),
            "messages": [
                serialize_message(conversation)
                for conversation in session.conversations.select_related("image_attachment").order_by("created_at", "id")
            ],
            "owner": {
                "username": session.owner.username,
            },
        },
        status=200,
    )


@login_required_json
@require_http_methods(["DELETE"])
def delete_session(request, session_id):
    session = get_owned_session_or_404(request, session_id)
    if session is None:
        return json_error("Session not found.", status=404)

    clear_history_cache(session.id)
    session.delete()
    return JsonResponse({"success": True}, status=200)


__all__ = [
    "app_shell",
    "service_worker",
    "web_manifest",
    "auth_status",
    "register_user",
    "login_user",
    "logout_user",
    "models_catalog",
    "background_job_list",
    "background_job_detail",
    "learning_quiz_sessions",
    "learning_quiz_detail",
    "delete_learning_quiz",
    "create_learning_quiz",
    "answer_learning_quiz_question",
    "create_learning_path",
    "create_roast",
    "create_fortune",
    "chat_post",
    "upload_chat_document",
    "upload_chat_image",
    "select_chat_document",
    "select_chat_image",
    "deactivate_chat_document",
    "deactivate_chat_image",
    "delete_chat_document",
    "delete_chat_image",
    "chat_stream",
    "chat_sessions",
    "chat_history_conversations",
    "public_chat_history",
    "edit_message",
    "regenerate_message",
    "toggle_session_pin",
    "toggle_session_visibility",
    "stop_chat_stream",
    "delete_session",
    "cloud_usage_stats",
    "cloud_usage_by_model",
]
