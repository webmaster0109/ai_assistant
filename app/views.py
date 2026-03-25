from django.shortcuts import render
# from .ollama import ollama_client, load_models, conversations
from django.http import JsonResponse
import markdown
from .langchain import conversation_chain, generate_title
from .models import ChatSession, ChatConversations
from .utils import cloud_usage_stats, usage_stats
import json


def api_ai_message(request, session_id):
  messages = ChatConversations.objects.filter(session_id=session_id).values('session__model', 'ai_message', 'user_message')
  # print(messages.query)
  # for msg in messages: pass
  # print(len(connection.queries))
  return JsonResponse({"model": list(messages)[0]['session__model'], "user_message": list(messages)[0]['user_message'], "ai_message": list(messages)[0]['ai_message']
  }, safe=False, status=200)

def chat_convo(request):
  return render(request, template_name="chat.html")

def chat_post(request):
    message = request.POST.get("message")
    model = request.POST.get("model")
    session_id = request.POST.get("session_id")

    if session_id:
      session = ChatSession.objects.filter(id=session_id).first()
      if not session:
        return JsonResponse({"error": "Session not found"}, status=404)
      model = session.model
    else:
      title = generate_title(message)
      session = ChatSession.objects.create(model=model, title=title)
    
    
    response, usage = conversation_chain(model, message, session_id=session.id)

    html_response = markdown.markdown(
      response,
      extensions=["fenced_code", "codehilite", "tables"]
    )

    ChatConversations.objects.create(
        session=session,
        user_message=message,
        ai_message=html_response,
        input_tokens=usage.get('input_tokens', 0),
        output_tokens=usage.get('output_tokens', 0)
      )
    
    usage = usage_stats()
    print(f"[DEBUG] usage: {usage}")
    print(f"[DEBUG] session_id: {session.id} | message: {message} | model: {model}")
    return JsonResponse({
      "user_message": message, 
      "ai_message": html_response, 
      "session_id": session.id,
      "title": session.title,
      "model": session.model.upper(),
      "model_key": session.model,
      "input_tokens": usage.get('input_tokens', 0),
      "output_tokens": usage.get('output_tokens', 0),
      "total_tokens": (usage.get('input_tokens', 0) + usage.get('output_tokens', 0)),
      }, status=200)


def chat_history_conversations(request, session_id):
  try:
    session = ChatSession.objects.get(id=session_id)
  except ChatSession.DoesNotExist:
    return JsonResponse({"error": "Session not found"}, status=404)
  
  conversations = list(
    ChatConversations.objects.filter(
        session_id=session_id
      ).values(
        'session__id',
        'session__title',
        'session__model',
        'ai_message',
        'user_message',
        'created_at'
      ).order_by('created_at')
  )
  # for convo in conversations:
  #   convo['ai_message'] = markdown.markdown(
  #     convo['ai_message'], 
  #     extensions=["fenced_code", "codehilite", "tables"]
  #   )
  return JsonResponse(conversations, safe=False, status=200)

def chat_sessions(request):
  sessions = ChatSession.objects.values('id', 'title', 'model', 'created_at').order_by('-created_at')
  return JsonResponse(list(sessions), safe=False, status=200)

def delete_session(request, session_id):
  try:
    session = ChatSession.objects.get(id=session_id)
    session.delete()
    return JsonResponse({"message": "Session deleted"}, status=200)
  except ChatSession.DoesNotExist:
    return JsonResponse({"error": "Session not found"}, status=404)