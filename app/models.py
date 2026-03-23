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
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  def __str__(self):
      return self.user_message