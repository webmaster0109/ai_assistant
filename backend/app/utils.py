from collections import Counter

from django.conf import settings as django_settings
from django.core.cache import cache
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.utils import timezone

from .models import ChatConversations, WebsiteSettings

def get_system_prompt() -> str:
  """Fetches the system prompt from cache or database settings."""
  cache_key = "system_prompt"

  cached = cache.get(cache_key)
  if cached:
    return cached
  prompts = WebsiteSettings.objects.values('system_prompt').first()

  prompt = (prompts.get('system_prompt') or "").strip() \
    if prompts else ""
  
  if not prompt:
    prompt = "You are a helpful and precise assistant for answering user queries. Always use all available information to provide the best answer. If you don't know the answer, say you don't know. Be concise and clear in your responses."

  cache.set(cache_key, prompt, timeout=600)  # Cache for 1 hour
  return prompt


def get_website_settings(request):
  return get_website_branding()

def get_website_branding():
  settings = WebsiteSettings.objects.values(
    'website_name',
    'website_description',
    'website_favicon'
  ).first()
  return context_processors(None, settings)

def context_processors(request, settings):
  if settings is None:
    instance = WebsiteSettings.objects.create()
    settings = {
      'website_name': instance.website_name,
      'website_description': instance.website_description,
      'website_favicon': instance.website_favicon.name if instance.website_favicon else None,
    }
  return {
    'website_name': settings.get('website_name') or "Ollama AI",
    'website_description': settings.get('website_description') or "A powerful AI chatbot platform built with Django and Ollama API.",
    'website_favicon': (django_settings.MEDIA_URL + settings.get('website_favicon') if settings.get('website_favicon') else None),
  }

def usage_stats(user=None):
  conversations = ChatConversations.objects.all()
  if user is not None:
    conversations = conversations.filter(session__owner=user)

  stats = conversations.values('input_tokens', 'output_tokens').aggregate(
    total_input_tokens=Sum('input_tokens'),
    total_output_tokens=Sum('output_tokens'),
    total_conversations=Count('id')
  )
  return stats

def usage_by_model(user=None):
  conversations = ChatConversations.objects.all()
  if user is not None:
    conversations = conversations.filter(session__owner=user)

  rows = (
    conversations.values("session__model")
    .annotate(
      total_input_tokens=Sum("input_tokens"),
      total_output_tokens=Sum("output_tokens"),
      total_conversations=Count("id"),
    )
    .order_by("-total_input_tokens", "-total_output_tokens", "session__model")
  )

  data = []
  for row in rows:
    input_tokens = row["total_input_tokens"] or 0
    output_tokens = row["total_output_tokens"] or 0
    data.append({
      "model": row["session__model"],
      "total_input_tokens": input_tokens,
      "total_output_tokens": output_tokens,
      "total_tokens": input_tokens + output_tokens,
      "total_conversations": row["total_conversations"] or 0,
    })
  return data

def profile_dashboard_stats(user=None):
  conversations = ChatConversations.objects.all()
  if user is not None:
    conversations = conversations.filter(session__owner=user)

  total_messages = conversations.count()

  favorite_model_row = (
    conversations.values("session__model")
    .annotate(
      total_messages=Count("id"),
      total_input_tokens=Sum("input_tokens"),
      total_output_tokens=Sum("output_tokens"),
    )
    .order_by("-total_messages", "-total_input_tokens", "-total_output_tokens", "session__model")
    .first()
  )

  favorite_model = favorite_model_row["session__model"] if favorite_model_row else ""
  favorite_model_messages = favorite_model_row["total_messages"] if favorite_model_row else 0

  hourly_counts = Counter()
  for created_at in conversations.values_list("created_at", flat=True):
    local_dt = timezone.localtime(created_at)
    hourly_counts[local_dt.hour] += 1

  most_active_hour = None
  most_active_messages = 0
  if hourly_counts:
    most_active_hour, most_active_messages = sorted(
      hourly_counts.items(),
      key=lambda item: (-item[1], item[0]),
    )[0]

  most_active_time = ""
  if most_active_hour is not None:
    start = timezone.datetime(2000, 1, 1, most_active_hour, 0)
    end = timezone.datetime(2000, 1, 1, (most_active_hour + 1) % 24, 0)
    most_active_time = f"{start.strftime('%I %p')} - {end.strftime('%I %p')}"

  return {
    "total_messages": total_messages,
    "favorite_model": favorite_model,
    "favorite_model_messages": favorite_model_messages,
    "most_active_time": most_active_time,
    "most_active_time_messages": most_active_messages,
  }

def cloud_usage_stats(request):
  if not request.user.is_authenticated:
    return JsonResponse({'detail': 'Authentication required.'}, status=401)

  stats = usage_stats(user=request.user)
  total_tokens = (stats['total_input_tokens'] or 0) + (stats['total_output_tokens'] or 0)
  dashboard = profile_dashboard_stats(user=request.user)
  return JsonResponse({
    'total_input_tokens': stats['total_input_tokens'] or 0,
    'total_output_tokens': stats['total_output_tokens'] or 0,
    'total_tokens': total_tokens,
    'total_conversations': stats['total_conversations'] or 0,
    'dashboard': {
      'total_messages': dashboard['total_messages'],
      'favorite_model': dashboard['favorite_model'] or "No activity yet",
      'favorite_model_messages': dashboard['favorite_model_messages'],
      'most_active_time': dashboard['most_active_time'] or "No activity yet",
      'most_active_time_messages': dashboard['most_active_time_messages'],
    },
  }, status=200)

def cloud_usage_by_model(request):
  if not request.user.is_authenticated:
    return JsonResponse({'detail': 'Authentication required.'}, status=401)

  return JsonResponse({
    "models": usage_by_model(user=request.user),
  }, status=200)
