import json
import uuid
from functools import wraps

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
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
from .models import ChatConversations, ChatSession
from .ollama import list_models
from .utils import cloud_usage_by_model, cloud_usage_stats, get_website_branding


User = get_user_model()
MAX_PINNED_SESSIONS = 3


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
        "is_pinned": session.is_pinned,
        "is_public": session.is_public,
        "share_url": build_share_path(session),
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "preview": latest_conversation.user_message[:120] if latest_conversation else "",
    }


def serialize_message(message):
    return {
        "id": message.id,
        "session_id": message.session_id,
        "user_message": message.user_message,
        "ai_message": message.ai_message,
        "input_tokens": message.input_tokens,
        "output_tokens": message.output_tokens,
        "created_at": message.created_at.isoformat(),
    }


def get_owned_session_or_404(request, session_id):
    return ChatSession.objects.filter(owner=request.user, id=session_id).first()


def get_public_session_or_404(share_token):
    return ChatSession.objects.filter(is_public=True, share_token=share_token).first()


def ordered_sessions_for_user(user):
    return (
        ChatSession.objects.filter(owner=user)
        .prefetch_related("conversations")
        .order_by("-is_pinned", "-updated_at")
    )


@ensure_csrf_cookie
@require_GET
def app_shell(request):
    return render(request, "app.html")


@require_GET
def service_worker(request):
    content = render_to_string("sw.js")
    return HttpResponse(content, content_type="application/javascript")


@require_GET
def web_manifest(request):
    branding = get_website_branding()
    icons = []
    if branding.get("website_favicon"):
        icons = [
            {
                "src": branding["website_favicon"],
                "sizes": "192x192",
                "purpose": "any",
            },
            {
                "src": branding["website_favicon"],
                "sizes": "512x512",
                "purpose": "any maskable",
            },
        ]
    else:
        icons = [
            {
                "src": "/static/frontend/pwa-icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable",
            },
        ]

    return JsonResponse(
        {
            "name": branding.get("website_name") or "Ollama AI",
            "short_name": branding.get("website_name") or "Ollama AI",
            "description": branding.get("website_description") or "Private AI chat workspace",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#0c1116",
            "theme_color": "#17594a",
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
def chat_sessions(request):
    sessions = ordered_sessions_for_user(request.user)
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
            "messages": [serialize_message(item) for item in session.conversations.order_by("created_at", "id")],
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
                for conversation in session.conversations.order_by("created_at", "id")
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
    "chat_post",
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
