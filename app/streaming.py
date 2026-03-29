from django.http import StreamingHttpResponse, JsonResponse
from .langchain import conversation_chain_stream
import json
import markdown
from .views import ChatConversations, generate_title, ChatSession


def chat_stream(request):
  """Streaming endpoints"""

  if request.method != 'POST':
    return JsonResponse({'error': 'POST method only'}, status=405)
  
  message = request.POST.get('message')
  model = request.POST.get('model')
  session_id = request.POST.get('session_id')

  if session_id:
    session = ChatConversations.objects.filter(id=session_id).first()
    if not session:
      return JsonResponse({'error': 'Session not found'}, status=404)
    model = session.model
  else:
    title = generate_title(message)
    session = ChatSession.objects.create(
      model=model,
      title=title
    )
  
  def event_stream():
    full_response = ""

    