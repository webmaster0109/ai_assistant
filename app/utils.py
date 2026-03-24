from . import prompts
from .models import WebsiteSettings

SYSTEM_PROMPTS = prompts.system_prompt

def get_website_settings(request):
  settings = WebsiteSettings.objects.first()
  return context_processors(request, settings)

def context_processors(request, settings):
  if settings is None:
    settings = WebsiteSettings.objects.create()
  return {
    'website_name': settings.website_name or "Ollama AI",
    'website_description': settings.website_description or "A powerful AI chatbot platform built with Django and Ollama API.",
    'website_logo': settings.website_logo.url if settings.website_logo else None,
    'website_favicon': settings.website_favicon.url if settings.website_favicon else None,
  }