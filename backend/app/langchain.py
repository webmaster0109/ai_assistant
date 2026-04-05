# from langchain_community.chat_models import ChatOllama
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
# from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.messages import SystemMessage
from .ollama import load_models
import os
from dotenv import load_dotenv
from .models import ChatConversations
from .utils import get_system_prompt

from django.core.cache import cache
import pickle
import re

load_dotenv()

# Persists across requests for the lifetime of the Django process
# store = {}
MAX_MESSAGES = 20
STREAM_STOP_TTL = 600
STREAM_TOKEN_PATTERN = re.compile(r"\s+|[^\s]+")

def history_cache_key(session_id: str) -> str:
  return f"history_{session_id}"

def stream_stop_cache_key(stream_id: str) -> str:
  return f"stream_stop_{stream_id}"

def clear_history_cache(session_id: str):
  cache.delete(history_cache_key(session_id))

def request_stream_stop(stream_id: str):
  cache.set(stream_stop_cache_key(stream_id), True, timeout=STREAM_STOP_TTL)

def clear_stream_stop(stream_id: str):
  cache.delete(stream_stop_cache_key(stream_id))

def should_stop_stream(stream_id: str) -> bool:
  return bool(cache.get(stream_stop_cache_key(stream_id)))

def cache_history(session_id: str, history: ChatMessageHistory):
  cache.set(history_cache_key(session_id), pickle.dumps(history), timeout=3600)

def load_history_from_db(session_id: str, exclude_conversation_id=None) -> ChatMessageHistory:
  cache_key = history_cache_key(session_id)
  if exclude_conversation_id is None:
    cached = cache.get(cache_key)
    if cached:
      print(f"[DEBUG] Cache hit for session_id: {session_id}")
      return pickle.loads(cached)

  history = ChatMessageHistory()
  conversations_qs = ChatConversations.objects.filter(session_id=session_id)
  if exclude_conversation_id is not None:
    conversations_qs = conversations_qs.exclude(id=exclude_conversation_id)

  conversations = conversations_qs.order_by('-created_at')[:MAX_MESSAGES]

  for convo in reversed(conversations):
    history.add_user_message(convo.user_message)
    history.add_ai_message(convo.ai_message)

  if exclude_conversation_id is None:
    cache_history(session_id, history)
  return history

def set_session_history(session_id: str, question: str, answer: str, exclude_conversation_id=None):
  history = load_history_from_db(session_id, exclude_conversation_id=exclude_conversation_id)
  history.add_user_message(question)
  history.add_ai_message(answer)

  if len(history.messages) > MAX_MESSAGES:
    history.messages = history.messages[-MAX_MESSAGES:]

  cache_history(session_id, history)

def load_regeneration_history(session_id: str, conversation_id: int) -> ChatMessageHistory:
  return load_history_from_db(session_id, exclude_conversation_id=conversation_id)

def iter_stream_chunks(content: str):
  parts = STREAM_TOKEN_PATTERN.findall(content or "")
  if not parts:
    return [content] if content else []
  return parts

def conversation_chain(models, question, session_id="default", history=None):
  system_prompt = get_system_prompt()

  prompt = ChatPromptTemplate.from_messages([
      SystemMessage(content=system_prompt),
      MessagesPlaceholder(variable_name="history"),
      ("human", "{input}"),
  ])

  llm = ChatOllama(
      model=load_models(models),
      base_url=os.getenv("OLLAMA_HOST"),
      headers={"Authorization": "Bearer " + os.getenv("OLLAMA_API_KEY")},
      temperature=0.7,
      num_predict=4096,
      num_ctx=8192,
  )

  chain = prompt | llm
  resolved_history = history or load_history_from_db(session_id)

  result = chain.invoke({
      "input": question,
      "history": resolved_history.messages,
  })

  usage = {}
  if hasattr(result, "response_metadata"):
      meta = result.response_metadata
      usage = {
          "input_tokens": meta.get("prompt_eval_count", 0),
          "output_tokens": meta.get("eval_count", 0),
      }
  return result.content, usage
  # history = ChatMessageHistory()

  # # ✅ Get latest MAX_MESSAGES, then reverse to chronological
  # conversations = list(
  #     ChatConversations.objects.filter(
  #         session_id=session_id
  #     ).order_by('-created_at')[:MAX_MESSAGES]
  # )[::-1]  # reverse to oldest → newest
  
  # print(f"[DEBUG] conversations from DB: {len(conversations)}")

  # for convo in conversations:
  #   history.add_user_message(convo.user_message)
  #   history.add_ai_message(convo.ai_message)

  # store[session_id] = history
  # return history

def generate_title(question):
  llm = ChatOllama(
    model=load_models('glm-5'),
    base_url=os.getenv("OLLAMA_HOST"),
    headers={"Authorization": "Bearer " + os.getenv("OLLAMA_API_KEY")},
    temperature=0.7,
  )
  prompt = ChatPromptTemplate.from_messages([
        ("system", 
         "Generate a short, concise chat title (max 6 words) for the following user message. "
         "Return only the title, no quotes, no explanation."),
        ("human", "{input}"),
    ])
  chain = prompt | llm
  return chain.invoke({"input": question}).content.strip()


def conversation_chain_stream(models, question, session_id="default", stream_id=None):
    """Stream chunks and emit a final payload with usage and stop status."""

    system_prompt = get_system_prompt()
    
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=system_prompt),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{input}"),
    ])

    llm = ChatOllama(
        model=load_models(models),
        base_url=os.getenv("OLLAMA_HOST"),
        headers={"Authorization": "Bearer " + os.getenv("OLLAMA_API_KEY")},
        temperature=0.7,
        num_predict=4096,
        num_ctx=8192
    )

    chain = prompt | llm
    history = load_history_from_db(session_id)
    full_response = ""
    usage = {
      "input_tokens": 0,
      "output_tokens": 0,
    }
    stopped = False

    for chunk in chain.stream({
        "input": question,
        "history": history.messages,
    }):
        if stream_id and should_stop_stream(stream_id):
          stopped = True
          break

        content = chunk.content
        if content:
          full_response += content
          for piece in iter_stream_chunks(content):
            yield {
              "type": "chunk",
              "content": piece,
            }

        if hasattr(chunk, "response_metadata"):
          meta = chunk.response_metadata or {}
          usage = {
            "input_tokens": meta.get("prompt_eval_count", usage["input_tokens"]),
            "output_tokens": meta.get("eval_count", usage["output_tokens"]),
          }

    if stream_id:
      clear_stream_stop(stream_id)

    yield {
      "type": "final",
      "content": full_response,
      "usage": usage,
      "stopped": stopped,
    }
