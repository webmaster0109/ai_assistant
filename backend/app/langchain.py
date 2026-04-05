# from langchain_community.chat_models import ChatOllama
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
# from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.messages import SystemMessage
from .ollama import load_models
import os
import json
import uuid
from dotenv import load_dotenv
from .models import ChatConversations
from .utils import get_system_prompt
from .documents import build_document_context

from django.core.cache import cache
import pickle
import re

load_dotenv()

# Persists across requests for the lifetime of the Django process
# store = {}
MAX_MESSAGES = 20
STREAM_STOP_TTL = 600
STREAM_TOKEN_PATTERN = re.compile(r"\s+|[^\s]+")
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)

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

def create_llm(model_key, temperature=0.7, num_predict=4096, num_ctx=8192):
  return ChatOllama(
      model=load_models(model_key),
      base_url=os.getenv("OLLAMA_HOST"),
      headers={"Authorization": "Bearer " + os.getenv("OLLAMA_API_KEY")},
      temperature=temperature,
      num_predict=num_predict,
      num_ctx=num_ctx,
  )

def extract_json_payload(content: str):
  text = str(content or "").strip()
  if not text:
    raise ValueError("The model returned an empty response.")

  fence_match = JSON_BLOCK_RE.search(text)
  if fence_match:
    text = fence_match.group(1).strip()

  if text.startswith("{") and text.endswith("}"):
    return json.loads(text)
  if text.startswith("[") and text.endswith("]"):
    return json.loads(text)

  object_start = text.find("{")
  object_end = text.rfind("}")
  if object_start != -1 and object_end != -1 and object_end > object_start:
    return json.loads(text[object_start:object_end + 1])

  array_start = text.find("[")
  array_end = text.rfind("]")
  if array_start != -1 and array_end != -1 and array_end > array_start:
    return json.loads(text[array_start:array_end + 1])

  raise ValueError("The model did not return valid JSON.")

def invoke_json_generation(model_key, system_prompt: str, user_prompt: str, temperature=0.4):
  llm = create_llm(model_key, temperature=temperature, num_predict=3072, num_ctx=8192)
  prompt = ChatPromptTemplate.from_messages([
      ("system", system_prompt),
      ("human", "{input}"),
  ])
  chain = prompt | llm
  result = chain.invoke({"input": user_prompt})
  return extract_json_payload(result.content)

def normalize_quiz_questions(payload, question_count: int):
  questions = payload.get("questions") if isinstance(payload, dict) else payload
  if not isinstance(questions, list):
    raise ValueError("Quiz questions were not returned in the expected format.")

  normalized = []
  for index, item in enumerate(questions[:question_count], start=1):
    options = item.get("options") or {}
    normalized.append({
      "question_text": str(item.get("question") or item.get("question_text") or "").strip(),
      "option_a": str(options.get("A") or item.get("option_a") or "").strip(),
      "option_b": str(options.get("B") or item.get("option_b") or "").strip(),
      "option_c": str(options.get("C") or item.get("option_c") or "").strip(),
      "option_d": str(options.get("D") or item.get("option_d") or "").strip(),
      "correct_option": str(item.get("correct_option") or "").strip().upper()[:1],
      "explanation": str(item.get("explanation") or "").strip(),
      "sort_order": index,
    })

  valid = []
  for item in normalized:
    if (
      item["question_text"]
      and item["option_a"]
      and item["option_b"]
      and item["option_c"]
      and item["option_d"]
      and item["correct_option"] in {"A", "B", "C", "D"}
    ):
      valid.append(item)

  if len(valid) < question_count:
    raise ValueError("The quiz generator returned incomplete questions. Please try again.")

  return valid

def generate_quiz_questions(model_key: str, topic: str, question_count=5, previous_questions=None):
  previous_questions = [str(item).strip() for item in (previous_questions or []) if str(item).strip()]
  variation_tag = uuid.uuid4().hex[:8]
  payload = invoke_json_generation(
    model_key,
    (
      "Create a multiple-choice quiz in strict JSON only. "
      "Return an object with a single key named questions. "
      "Each question must include: question, options with keys A/B/C/D, correct_option, explanation. "
      "Make the quiz practical, beginner-friendly, and accurate. "
      "Do not include markdown or prose outside JSON."
    ),
    (
      f"Topic: {topic}\n"
      f"Question count: {question_count}\n"
      f"Variation tag: {variation_tag}\n"
      + (
        "Avoid repeating any of these older questions or their close paraphrases:\n"
        + "\n".join(f"- {item}" for item in previous_questions[:30])
        + "\n"
        if previous_questions else ""
      )
      + "Keep each option concise and make only one answer correct. "
        "Use fresh angles, examples, and wording for this new quiz."
    ),
    temperature=0.35,
  )
  return normalize_quiz_questions(payload, question_count)

def generate_learning_path(model_key: str, goal: str, experience_level: str, weekly_hours: str, timeline: str):
  payload = invoke_json_generation(
    model_key,
    (
      "Build a personalized learning roadmap in strict JSON only. "
      "Return an object with title, summary, first_steps, and milestones. "
      "first_steps must be an array of short strings. "
      "milestones must be an array of objects with title, duration, focus, deliverable. "
      "Do not include markdown or prose outside JSON."
    ),
    (
      f"Learning goal: {goal}\n"
      f"Experience level: {experience_level or 'Not specified'}\n"
      f"Weekly hours available: {weekly_hours or 'Not specified'}\n"
      f"Preferred timeline: {timeline or 'Not specified'}\n"
      "Keep the roadmap practical, milestone-based, and realistic."
    ),
    temperature=0.4,
  )

  milestones = payload.get("milestones") or []
  normalized_milestones = []
  for item in milestones:
    normalized_milestones.append({
      "title": str(item.get("title") or "").strip(),
      "duration": str(item.get("duration") or "").strip(),
      "focus": str(item.get("focus") or "").strip(),
      "deliverable": str(item.get("deliverable") or "").strip(),
    })

  normalized_first_steps = [
    str(item).strip()
    for item in (payload.get("first_steps") or [])
    if str(item).strip()
  ]

  if not str(payload.get("title") or "").strip() or not normalized_milestones:
    raise ValueError("The learning path generator returned incomplete data. Please try again.")

  return {
    "title": str(payload.get("title") or "").strip(),
    "summary": str(payload.get("summary") or "").strip(),
    "first_steps": normalized_first_steps,
    "milestones": [
      item for item in normalized_milestones
      if item["title"] and item["duration"] and item["focus"] and item["deliverable"]
    ],
  }

def build_chat_system_prompt(base_prompt: str, document_context: str = "") -> str:
  if not document_context:
    return base_prompt

  return (
    f"{base_prompt}\n\n"
    "The user has uploaded a PDF for this chat. Use the document context below when answering. "
    "If the answer is not supported by the document context, say that clearly instead of inventing details.\n\n"
    f"Document context:\n{document_context}"
  )

def conversation_chain(models, question, session_id="default", history=None):
  system_prompt = get_system_prompt()
  document_context = build_document_context(session_id, question)
  resolved_system_prompt = build_chat_system_prompt(system_prompt, document_context)

  prompt = ChatPromptTemplate.from_messages([
      SystemMessage(content=resolved_system_prompt),
      MessagesPlaceholder(variable_name="history"),
      ("human", "{input}"),
  ])

  llm = create_llm(models)

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
    document_context = build_document_context(session_id, question)
    resolved_system_prompt = build_chat_system_prompt(system_prompt, document_context)
    
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=resolved_system_prompt),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{input}"),
    ])

    llm = create_llm(models)

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
