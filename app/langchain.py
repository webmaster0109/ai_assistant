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

load_dotenv()

# Persists across requests for the lifetime of the Django process
# store = {}
MAX_MESSAGES = 20

def load_history_from_db(session_id: str) -> ChatMessageHistory:
  cache_key = f"history_{session_id}"
  cached = cache.get(cache_key)
  if cached:
    print(f"[DEBUG] Cache hit for session_id: {session_id}")
    return pickle.loads(cached)
  history = ChatMessageHistory()
  conversations = ChatConversations.objects.filter(
     session_id=session_id
  ).order_by('-created_at')[:MAX_MESSAGES]

  for convo in reversed(conversations):
     history.add_user_message(convo.user_message)
     history.add_ai_message(convo.ai_message)

  cache.set(cache_key, pickle.dumps(history), timeout=3600)
  return history
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


def conversation_chain_stream(models, question, session_id="default"):
    """ for Streaming - yield chunks """

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

    for chunk in chain.stream({
        "input": question,
        "history": history.messages,
    }):
        content = chunk.content
        if content:
          full_response += content
          yield content

    history.add_user_messages(question)
    history.add_ai_messages(full_response)

    if len(history.messages) > MAX_MESSAGES:
       history.messages = history.messages[-MAX_MESSAGES:]

def conversation_chain(models, question, session_id="default"):

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
        # system=system_prompt
        # response length
        num_predict=4096,  
        # total context window (history + response)
        num_ctx=8192,
    )
      
    # runnable = RunnableWithMessageHistory(
    #    prompt | llm,
    #    # get_trimmed_session_history,
    #    load_history_from_db,
    #    input_messages_key="input",
    #    history_messages_key="history",
    # )

    # config = {"configurable": {"session_id": session_id}}
    # lang_result = runnable.invoke({"input": question}, config=config)

    chain = prompt | llm
    history = load_history_from_db(session_id)

    result = chain.invoke({
        "input": question,
        "history": history.messages,
    })

    usage = {}
    if hasattr(result, "response_metadata"):
        meta = result.response_metadata
        usage = {
            "input_tokens": meta.get("prompt_eval_count", 0),
            "output_tokens": meta.get("eval_count", 0),
        }
    return result.content, usage