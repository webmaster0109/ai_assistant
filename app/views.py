import json
from functools import wraps

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods

from .langchain import conversation_chain, generate_title
from .models import ChatConversations, ChatSession
from .ollama import list_models
from .utils import cloud_usage_stats, get_website_branding


User = get_user_model()


def parse_request_data(request):
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}
    return request.POST


def json_error(message, status=400):
    return JsonResponse({"detail": message}, status=status)


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


def serialize_session(session):
    latest_conversation = session.conversations.order_by("-created_at").first()
    return {
        "id": session.id,
        "title": session.title,
        "model": session.model,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "preview": latest_conversation.user_message[:120] if latest_conversation else "",
    }


def serialize_message(message):
    return {
        "id": message.id,
        "user_message": message.user_message,
        "ai_message": message.ai_message,
        "input_tokens": message.input_tokens,
        "output_tokens": message.output_tokens,
        "created_at": message.created_at.isoformat(),
    }


def get_owned_session_or_404(request, session_id):
    return ChatSession.objects.filter(owner=request.user, id=session_id).first()


@ensure_csrf_cookie
@require_GET
def app_shell(request):
    return render(request, "app.html")


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
def chat_sessions(request):
    sessions = (
        ChatSession.objects.filter(owner=request.user)
        .prefetch_related("conversations")
        .order_by("-updated_at")
    )
    return JsonResponse({"sessions": [serialize_session(session) for session in sessions]}, status=200)


@login_required_json
@require_GET
def chat_history_conversations(request, session_id):
    session = get_owned_session_or_404(request, session_id)
    if session is None:
        return json_error("Session not found.", status=404)

    conversations = session.conversations.order_by("created_at")
    return JsonResponse(
        {
            "session": serialize_session(session),
            "messages": [serialize_message(conversation) for conversation in conversations],
        },
        status=200,
    )


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

    response, usage = conversation_chain(model, message, session_id=session.id)
    conversation = ChatConversations.objects.create(
        session=session,
        user_message=message,
        ai_message=response,
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
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
@require_http_methods(["DELETE"])
def delete_session(request, session_id):
    session = get_owned_session_or_404(request, session_id)
    if session is None:
        return json_error("Session not found.", status=404)

    session.delete()
    return JsonResponse({"success": True}, status=200)


__all__ = [
    "app_shell",
    "auth_status",
    "register_user",
    "login_user",
    "logout_user",
    "models_catalog",
    "chat_post",
    "chat_sessions",
    "chat_history_conversations",
    "delete_session",
    "cloud_usage_stats",
]
