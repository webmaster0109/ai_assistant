from django.conf import settings as django_settings
from django.core.cache import cache
from django.db.models import Count, Sum
from django.http import JsonResponse

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

def cloud_usage_stats(request):
  if not request.user.is_authenticated:
    return JsonResponse({'detail': 'Authentication required.'}, status=401)

  stats = usage_stats(user=request.user)
  total_tokens = (stats['total_input_tokens'] or 0) + (stats['total_output_tokens'] or 0)
  return JsonResponse({
    'total_input_tokens': stats['total_input_tokens'] or 0,
    'total_output_tokens': stats['total_output_tokens'] or 0,
    'total_tokens': total_tokens,
    'total_conversations': stats['total_conversations'] or 0,
  }, status=200)

def cloud_usage_by_model(request):
  if not request.user.is_authenticated:
    return JsonResponse({'detail': 'Authentication required.'}, status=401)

  return JsonResponse({
    "models": usage_by_model(user=request.user),
  }, status=200)
