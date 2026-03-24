from . import prompts
from .models import WebsiteSettings, ChatConversations
from django.db.models import Sum, Count
from django.http import JsonResponse
from django.conf import settings as django_settings



SYSTEM_PROMPTS = prompts.system_prompt

def get_website_settings(request):
  settings = WebsiteSettings.objects.values(
    'website_name', 
    'website_description', 
    'website_favicon'
  ).first()
  return context_processors(request, settings)

def context_processors(request, settings):
  if settings is None:
    settings = WebsiteSettings.objects.create()
  return {
    'website_name': settings.get('website_name') or "Ollama AI",
    'website_description': settings.get('website_description') or "A powerful AI chatbot platform built with Django and Ollama API.",
    'website_favicon': (django_settings.MEDIA_URL + settings.get('website_favicon') if settings.get('website_favicon') else None),
  }

def cloud_usage_stats(request):
  stats = ChatConversations.objects.aggregate(
    total_input_tokens=Sum('input_tokens'),
    total_output_tokens=Sum('output_tokens'),
    total_conversations=Count('id')
  )
  total_tokens = (stats['total_input_tokens'] or 0) + (stats['total_output_tokens'] or 0)
  return JsonResponse({
    'total_input_tokens': stats['total_input_tokens'] or 0,
    'total_output_tokens': stats['total_output_tokens'] or 0,
    'total_tokens': total_tokens,
    'total_conversations': stats['total_conversations'] or 0,
  }, status=200)