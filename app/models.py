from django.db import models
import uuid
# import signals
from django.db.models.signals import post_save
from django.dispatch import receiver
# Create your models here.

def generate_uuid():
  return str(uuid.uuid4()).replace("-", "")

class ChatSession(models.Model):
  id = models.CharField(primary_key=True, default=generate_uuid, editable=False)
  model = models.CharField(max_length=100)
  title = models.CharField(max_length=100)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  def __str__(self):
      return f"{self.model} - {self.title}"

class ChatConversations(models.Model):
  session = models.ForeignKey(
    ChatSession, 
    on_delete=models.CASCADE, 
    related_name="conversations"
  )
  user_message = models.TextField()
  ai_message = models.TextField()
  # image field for future use
  image = models.ImageField(upload_to='vision/images/', null=True, blank=True)
  input_tokens = models.IntegerField(default=0)   # prompt_eval_count
  output_tokens = models.IntegerField(default=0)  # eval_count
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  def __str__(self):
      return self.user_message


class WebsiteSettings(models.Model):
   website_name = models.CharField(max_length=100, default="Ollama AI")
   website_logo = models.ImageField(upload_to='logos/', null=True, blank=True)
   website_favicon = models.ImageField(upload_to='favicons/', null=True, blank=True)
   website_description = models.TextField(default="A powerful AI chatbot platform built with Django and Ollama API.")
   
   maintainance_mode = models.BooleanField(default=False)

   def __str__(self):
      return self.website_name