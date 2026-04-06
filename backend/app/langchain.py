# from langchain_community.chat_models import ChatOllama
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
# from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from .ollama import load_models, ollama_client
import os
import json
import uuid
import base64
from dotenv import load_dotenv
from .models import ChatConversations
from .utils import get_system_prompt
from .documents import build_document_context

from django.core.cache import cache
import pickle
import re
import time

load_dotenv()

# Persists across requests for the lifetime of the Django process
# store = {}
MAX_MESSAGES = 20
STREAM_STOP_TTL = 600
STREAM_TOKEN_PATTERN = re.compile(r"\s+|[^\s]+")
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
TRANSIENT_GENERATION_ERROR_MARKERS = (
  "connection aborted",
  "connection reset by peer",
  "temporarily unavailable",
  "remote end closed connection",
  "read timed out",
  "timed out",
  "connection refused",
  "502",
  "503",
  "504",
)

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

  conversations = conversations_qs.only("user_message", "ai_message", "created_at").order_by('-created_at', '-id')[:MAX_MESSAGES]

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

def encode_file_as_base64(file_field):
  if not file_field:
    return ""

  with file_field.open("rb") as stored_file:
    return base64.b64encode(stored_file.read()).decode("utf-8")

def history_to_ollama_messages(history_messages):
  messages = []
  for item in history_messages or []:
    if isinstance(item, SystemMessage):
      role = "system"
    elif isinstance(item, AIMessage):
      role = "assistant"
    else:
      role = "user"

    content = item.content
    if isinstance(content, list):
      content = "\n".join(
        part.get("text", "")
        for part in content
        if isinstance(part, dict) and part.get("type") == "text"
      )
    messages.append({
      "role": role,
      "content": str(content or ""),
    })
  return messages

def extract_usage_from_ollama_payload(payload):
  if not isinstance(payload, dict):
    return {
      "input_tokens": 0,
      "output_tokens": 0,
    }

  return {
    "input_tokens": payload.get("prompt_eval_count", 0) or 0,
    "output_tokens": payload.get("eval_count", 0) or 0,
  }

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

def sanitize_json_text(text: str) -> str:
  source = str(text or "").strip()
  if not source:
    return source

  return re.sub(r",(\s*[}\]])", r"\1", source)

def is_transient_generation_error(error: Exception) -> bool:
  message = str(error or "").strip().casefold()
  if not message:
    return False
  return any(marker in message for marker in TRANSIENT_GENERATION_ERROR_MARKERS)

def invoke_json_generation(model_key, system_prompt: str, user_prompt: str, temperature=0.4):
  llm = create_llm(model_key, temperature=temperature, num_predict=3072, num_ctx=8192)
  prompt = ChatPromptTemplate.from_messages([
      ("system", system_prompt),
      MessagesPlaceholder(variable_name="history"),
      ("human", "{input}"),
  ])
  chain = prompt | llm
  history = []
  current_input = user_prompt
  last_error = None

  for attempt in range(3):
    result = None
    transport_error = None

    for transport_attempt in range(3):
      try:
        result = chain.invoke({
          "input": current_input,
          "history": history,
        })
        transport_error = None
        break
      except Exception as error:
        transport_error = error
        if not is_transient_generation_error(error) or transport_attempt == 2:
          break
        time.sleep(0.8 * (transport_attempt + 1))

    if transport_error is not None:
      raise ValueError(
        "The model connection was interrupted while generating the result. Please try again."
      ) from transport_error

    raw_content = str(result.content or "").strip()

    try:
      return extract_json_payload(raw_content)
    except (json.JSONDecodeError, ValueError) as error:
      last_error = error

      try:
        repaired_payload = extract_json_payload(sanitize_json_text(raw_content))
        return repaired_payload
      except (json.JSONDecodeError, ValueError):
        pass

      history.extend([
        AIMessage(content=raw_content),
        HumanMessage(
          content=
            "Your previous reply was not valid JSON. "
            f"Parser error: {error}. "
            "Return the same answer again as strict valid JSON only. "
            "Do not add markdown fences, comments, or explanation text."
        ),
      ])
      current_input = "Return strict valid JSON only."
      continue

  raise ValueError(f"The model returned invalid JSON after multiple attempts: {last_error}")

def normalize_option_map(options):
  if isinstance(options, dict):
    normalized = {}
    for key, value in options.items():
      normalized[str(key).strip().upper()[:1]] = str(value or "").strip()
    return normalized

  if isinstance(options, (list, tuple)):
    labels = ("A", "B", "C", "D")
    return {
      label: str(value or "").strip()
      for label, value in zip(labels, options[:4])
    }

  return {}

def resolve_correct_option(raw_value, option_map):
  value = str(raw_value or "").strip()
  if not value:
    return ""

  letter_match = re.search(r"\b([A-D])\b", value.upper())
  if letter_match:
    return letter_match.group(1)

  lowered_value = value.casefold()
  for label, option_text in option_map.items():
    if lowered_value == str(option_text or "").strip().casefold():
      return label

  return ""

def normalize_quiz_questions(payload, question_count: int, strict=True):
  questions = payload.get("questions") if isinstance(payload, dict) else payload
  if not isinstance(questions, list):
    raise ValueError("Quiz questions were not returned in the expected format.")

  normalized = []
  for index, item in enumerate(questions[:question_count], start=1):
    options = normalize_option_map(
      item.get("options")
      or item.get("choices")
      or item.get("answers")
      or {}
    )
    option_a = str(options.get("A") or item.get("option_a") or "").strip()
    option_b = str(options.get("B") or item.get("option_b") or "").strip()
    option_c = str(options.get("C") or item.get("option_c") or "").strip()
    option_d = str(options.get("D") or item.get("option_d") or "").strip()
    resolved_options = {
      "A": option_a,
      "B": option_b,
      "C": option_c,
      "D": option_d,
    }
    normalized.append({
      "question_text": str(item.get("question") or item.get("question_text") or "").strip(),
      "option_a": option_a,
      "option_b": option_b,
      "option_c": option_c,
      "option_d": option_d,
      "correct_option": resolve_correct_option(
        item.get("correct_option") or item.get("answer") or item.get("correct_answer") or "",
        resolved_options,
      ),
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

  if strict and len(valid) < question_count:
    raise ValueError("The quiz generator returned incomplete questions. Please try again.")

  return valid

def generate_quiz_questions(model_key: str, topic: str, difficulty_level="beginner", question_count=5, previous_questions=None):
  previous_questions = [str(item).strip() for item in (previous_questions or []) if str(item).strip()]
  collected = []
  seen_questions = set()
  normalized_level = str(difficulty_level or "beginner").strip().lower()
  level_guidance = {
    "beginner": "Use very clear wording, foundational concepts, and straightforward examples.",
    "intermediate": "Use practical scenarios and combine related concepts without becoming overly tricky.",
    "advanced": "Use deeper reasoning, edge cases, and stronger conceptual comparisons.",
    "master": "Use expert-level tradeoffs, architecture thinking, and non-obvious pitfalls.",
    "enterprises mastery": "Use enterprise-scale scenarios, production constraints, maintainability, security, scalability, and team-level decision making.",
  }.get(normalized_level, "Use practical, accurate questions that match the requested difficulty.")

  for attempt in range(4):
    remaining = question_count - len(collected)
    if remaining <= 0:
      break

    variation_tag = uuid.uuid4().hex[:8]
    avoided_questions = previous_questions + [item["question_text"] for item in collected]
    payload = invoke_json_generation(
      model_key,
      (
        "Create a multiple-choice quiz in strict JSON only. "
        "Return an object with a single key named questions. "
        "Return exactly the requested number of questions. "
        "Each question must include: question, options with keys A/B/C/D, correct_option, explanation. "
        "Make the quiz practical, level-appropriate, and accurate. "
        "Do not include markdown or prose outside JSON."
      ),
      (
        f"Topic: {topic}\n"
        f"Difficulty level: {normalized_level}\n"
        f"Question count: {remaining}\n"
        f"Variation tag: {variation_tag}\n"
        + (
          "Avoid repeating any of these older questions or their close paraphrases:\n"
          + "\n".join(f"- {item}" for item in avoided_questions[:40])
          + "\n"
          if avoided_questions else ""
        )
        + f"Level guidance: {level_guidance}\n"
        + "Keep each option concise and make only one answer correct. "
          "Use fresh angles, examples, and wording for this new quiz."
      ),
      temperature=0.35,
    )

    normalized_batch = normalize_quiz_questions(payload, remaining, strict=False)
    for item in normalized_batch:
      question_key = item["question_text"].casefold()
      if not question_key or question_key in seen_questions:
        continue
      seen_questions.add(question_key)
      collected.append(item)
      if len(collected) >= question_count:
        break

  if len(collected) < question_count:
    if len(collected) >= 3:
      question_count = len(collected)
    else:
      raise ValueError("Unable to generate a complete quiz right now. Please try again.")

  for index, item in enumerate(collected[:question_count], start=1):
    item["sort_order"] = index

  return collected[:question_count]

def generate_learning_path(model_key: str, goal: str, experience_level: str, weekly_hours: str, timeline: str):
  normalized_level = str(experience_level or "beginner").strip().lower()
  level_guidance = {
    "beginner": "Assume the learner needs strong fundamentals, simple sequencing, clear milestones, and low-friction first projects.",
    "intermediate": "Assume the learner knows the basics and needs practical depth, stronger exercises, and project-based progression.",
    "advanced": "Assume the learner already has solid experience and needs deeper concepts, tradeoffs, optimization, and harder deliverables.",
    "master": "Assume the learner is highly skilled and wants expert mastery, nuanced decision making, architecture thinking, and research-level refinement.",
    "enterprises mastery": "Assume the learner wants enterprise-grade mastery with production systems, scale, reliability, governance, collaboration, and business-aware execution.",
  }.get(normalized_level, "Keep the roadmap aligned with the selected level.")

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
      f"Experience level: {normalized_level or 'Not specified'}\n"
      f"Weekly hours available: {weekly_hours or 'Not specified'}\n"
      f"Preferred timeline: {timeline or 'Not specified'}\n"
      f"Level guidance: {level_guidance}\n"
      "Keep the roadmap practical, milestone-based, realistic, and clearly matched to the selected level."
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

def generate_roast_analysis(model_key: str, content_type: str, content: str, language: str = "english", improvement_goal: str = ""):
  normalized_type = str(content_type or "auto").strip().lower()
  normalized_language = str(language or "english").strip().lower()
  language_instruction = {
    "english": "Write the roast, suggestions, and improved version fully in natural English.",
    "hindi": "Write the roast, suggestions, and improved version fully in natural Hindi only.",
    "nepali": "Write the roast, suggestions, and improved version fully in natural Nepali only.",
  }.get(normalized_language, "Write the roast in the requested language.")
  payload = invoke_json_generation(
    model_key,
    (
      "You are a witty but useful roast assistant. "
      "Roast the user's text, code, or message in a funny, sharp, non-abusive way. "
      "Return strict JSON only with keys: title, opening_line, roast_points, improvement_suggestions, improved_version. "
      "roast_points must be an array of short funny criticisms. "
      "improvement_suggestions must be an array of concise, practical fixes. "
      "improved_version must be a cleaner improved rewrite of the user's original content. "
      "Keep the roast playful, intelligent, and helpful, not hateful or slur-based. "
      f"{language_instruction} "
      "Do not include markdown or prose outside JSON."
    ),
    (
      f"Content type: {normalized_type}\n"
      f"Output language: {normalized_language}\n"
      f"Improvement goal: {improvement_goal or 'General improvement'}\n"
      "User content follows:\n"
      f"{content}"
    ),
    temperature=0.65,
  )

  roast_points = [
    str(item).strip()
    for item in (payload.get("roast_points") or [])
    if str(item).strip()
  ]
  improvement_suggestions = [
    str(item).strip()
    for item in (payload.get("improvement_suggestions") or [])
    if str(item).strip()
  ]
  improved_version = str(payload.get("improved_version") or "").strip()

  if not roast_points or not improvement_suggestions or not improved_version:
    raise ValueError("The roast generator returned incomplete data. Please try again.")

  return {
    "title": str(payload.get("title") or "").strip() or "Roast report",
    "opening_line": str(payload.get("opening_line") or "").strip(),
    "roast_points": roast_points,
    "improvement_suggestions": improvement_suggestions,
    "improved_version": improved_version,
  }

def generate_fortune_reading(model_key: str, question: str, focus_area: str = "general", language: str = "english"):
  normalized_focus = str(focus_area or "general").strip().lower()
  normalized_language = str(language or "english").strip().lower()
  language_instruction = {
    "english": "Write the fortune fully in natural English.",
    "hindi": "Write the fortune fully in natural Hindi only.",
    "nepali": "Write the fortune fully in natural Nepali only.",
  }.get(normalized_language, "Write the fortune in the requested language.")

  payload = invoke_json_generation(
    model_key,
    (
      "You are a mystical fortune teller for entertainment only. "
      "Speak in a magical, atmospheric, playful tone, but stay emotionally safe and non-harmful. "
      "Never present the reading as factual certainty, medical advice, legal advice, or financial certainty. "
      "Return strict JSON only with keys: title, opening_line, reading, lucky_signs, guidance_points, closing_line, disclaimer. "
      "lucky_signs must be an array of short symbolic signs or omens. "
      "guidance_points must be an array of short practical reflections. "
      f"{language_instruction} "
      "Keep it entertaining, imaginative, and clearly fortune-style."
    ),
    (
      f"Focus area: {normalized_focus}\n"
      f"Output language: {normalized_language}\n"
      "User's question or concern:\n"
      f"{question}"
    ),
    temperature=0.85,
  )

  lucky_signs = [
    str(item).strip()
    for item in (payload.get("lucky_signs") or [])
    if str(item).strip()
  ]
  guidance_points = [
    str(item).strip()
    for item in (payload.get("guidance_points") or [])
    if str(item).strip()
  ]
  reading = str(payload.get("reading") or "").strip()

  if not reading or not lucky_signs or not guidance_points:
    raise ValueError("The fortune teller returned incomplete data. Please try again.")

  return {
    "title": str(payload.get("title") or "").strip() or "Mystic reading",
    "opening_line": str(payload.get("opening_line") or "").strip(),
    "reading": reading,
    "lucky_signs": lucky_signs,
    "guidance_points": guidance_points,
    "closing_line": str(payload.get("closing_line") or "").strip(),
    "disclaimer": str(payload.get("disclaimer") or "").strip() or "Entertainment only.",
  }

def generate_movie_recommendations(
  model_key: str,
  mood: str,
  genre: str,
  country: str,
  extra_preferences: str = "",
  candidates=None,
):
  movie_candidates = [item for item in (candidates or []) if item.get("id") and item.get("title")]
  if len(movie_candidates) < 6:
    raise ValueError("Not enough movie candidates were available for recommendation.")

  candidate_lines = []
  for item in movie_candidates[:24]:
    candidate_lines.append(
      (
        f"{item['id']} | {item['title']} | {item.get('year') or 'Unknown year'} | "
        f"rating {item.get('rating') or 0} | "
        f"language {item.get('original_language') or 'unknown'} | "
        f"overview: {item.get('overview') or 'No overview available.'}"
      )
    )

  payload = invoke_json_generation(
    model_key,
    (
      "You are a high-quality movie recommendation curator. "
      "Pick only from the supplied TMDB candidate list. "
      "Return strict JSON only with keys: title, subtitle, picks. "
      "picks must be an array with 6 to 8 items. "
      "Each pick must include: id, why. "
      "The why field must be a short, vivid recommendation reason matched to the user's mood. "
      "Never invent IDs or movies outside the candidate list."
    ),
    (
      f"Mood: {mood}\n"
      f"Genre: {genre}\n"
      f"Country: {country}\n"
      f"Extra preferences: {extra_preferences or 'None'}\n"
      "Candidate list:\n"
      + "\n".join(candidate_lines)
    ),
    temperature=0.55,
  )

  raw_picks = payload.get("picks") or []
  candidate_map = {item["id"]: item for item in movie_candidates}
  selected = []
  seen_ids = set()

  for item in raw_picks:
    try:
      movie_id = int(item.get("id"))
    except (TypeError, ValueError, AttributeError):
      continue
    if movie_id in seen_ids or movie_id not in candidate_map:
      continue
    seen_ids.add(movie_id)
    selected.append({
      **candidate_map[movie_id],
      "why": str(item.get("why") or "").strip(),
    })
    if len(selected) >= 8:
      break

  if len(selected) < 6:
    for item in movie_candidates:
      if item["id"] in seen_ids:
        continue
      selected.append({
        **item,
        "why": "A strong match for the vibe, genre, and viewing mood you described.",
      })
      if len(selected) >= 6:
        break

  return {
    "title": str(payload.get("title") or "").strip() or "Your movie picks are ready",
    "subtitle": str(payload.get("subtitle") or "").strip() or "Curated with IMDB discovery and Gemma 4 taste-matching.",
    "picks": selected[:8],
  }

def build_chat_system_prompt(base_prompt: str, document_context: str = "", has_image=False) -> str:
  additions = []

  if has_image:
    additions.append(
      "The user may have attached an image for this turn. Use the image carefully and answer from what is visible in it. "
      "Do not pretend the image is missing if an image has been attached."
    )

  if document_context:
    additions.append(
      "The user has uploaded a PDF for this chat, and the document has already been ingested into the app. "
      "The context below is a retrieved evidence window from that uploaded PDF, not a claim that only those pages exist. "
      "Never say that only some pages were uploaded, never ask the user to provide all pages again, and never imply the PDF is only partially available just because the retrieved evidence references specific pages. "
      "Use the retrieved document evidence to answer accurately. "
      "If the current evidence window is not enough for a precise answer, say that you need to inspect another section of the already uploaded PDF, not that the user must upload or provide the pages again."
    )

  if not additions:
    return base_prompt

  prompt = f"{base_prompt}\n\n" + "\n\n".join(additions)
  if document_context:
    prompt += f"\n\nDocument context:\n{document_context}"
  return prompt

def multimodal_conversation_chain(model_key, question, history=None, system_prompt="", image_attachments=None):
  client = ollama_client()
  resolved_history = history.messages if hasattr(history, "messages") else (history or [])
  messages = [{"role": "system", "content": system_prompt}]
  messages.extend(history_to_ollama_messages(resolved_history))

  user_message = {
    "role": "user",
    "content": question,
  }
  images = [
    encode_file_as_base64(image.file)
    for image in (image_attachments or [])
    if getattr(image, "file", None)
  ]
  if images:
    user_message["images"] = images
  messages.append(user_message)

  response = client.chat(model=load_models(model_key), messages=messages)
  message = response.get("message") or {}
  return message.get("content", ""), extract_usage_from_ollama_payload(response)

def conversation_chain(models, question, session_id="default", history=None, image_attachments=None):
  system_prompt = get_system_prompt()
  document_context = build_document_context(session_id, question)
  resolved_system_prompt = build_chat_system_prompt(system_prompt, document_context, has_image=bool(image_attachments))
  resolved_history = history or load_history_from_db(session_id)

  if image_attachments:
    return multimodal_conversation_chain(
      models,
      question,
      history=resolved_history,
      system_prompt=resolved_system_prompt,
      image_attachments=image_attachments,
    )

  prompt = ChatPromptTemplate.from_messages([
      SystemMessage(content=resolved_system_prompt),
      MessagesPlaceholder(variable_name="history"),
      ("human", "{input}"),
  ])

  llm = create_llm(models)

  chain = prompt | llm

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


def conversation_chain_stream(models, question, session_id="default", stream_id=None, image_attachments=None):
    """Stream chunks and emit a final payload with usage and stop status."""

    system_prompt = get_system_prompt()
    document_context = build_document_context(session_id, question)
    resolved_system_prompt = build_chat_system_prompt(system_prompt, document_context, has_image=bool(image_attachments))
    history = load_history_from_db(session_id)

    if image_attachments:
      client = ollama_client()
      messages = [{"role": "system", "content": resolved_system_prompt}]
      messages.extend(history_to_ollama_messages(history.messages))
      user_message = {
        "role": "user",
        "content": question,
      }
      images = [
        encode_file_as_base64(image.file)
        for image in (image_attachments or [])
        if getattr(image, "file", None)
      ]
      if images:
        user_message["images"] = images
      messages.append(user_message)

      full_response = ""
      usage = {
        "input_tokens": 0,
        "output_tokens": 0,
      }
      stopped = False

      for chunk in client.chat(model=load_models(models), messages=messages, stream=True):
        if stream_id and should_stop_stream(stream_id):
          stopped = True
          break

        message = chunk.get("message") or {}
        content = message.get("content") or ""
        if content:
          full_response += content
          for piece in iter_stream_chunks(content):
            yield {
              "type": "chunk",
              "content": piece,
            }

        if chunk.get("done"):
          usage = extract_usage_from_ollama_payload(chunk)

      if stream_id:
        clear_stream_stop(stream_id)

      yield {
        "type": "final",
        "content": full_response,
        "usage": usage,
        "stopped": stopped,
      }
      return
    
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=resolved_system_prompt),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{input}"),
    ])

    llm = create_llm(models)

    chain = prompt | llm
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
