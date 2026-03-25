from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.messages import SystemMessage
from .ollama import load_models
import os
from dotenv import load_dotenv
from .models import ChatConversations
from .utils import SYSTEM_PROMPTS

load_dotenv()

# Persists across requests for the lifetime of the Django process
store = {}
MAX_MESSAGES = 20

def get_session_history(session_id: str) -> ChatMessageHistory:
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]

def get_trimmed_session_history(session_id: str) -> ChatMessageHistory:
  history = get_session_history(session_id)
  
  # Trim to last MAX_MESSAGES
  if len(history.messages) > MAX_MESSAGES:
    history.messages = history.messages[-MAX_MESSAGES:]
  return history

def load_history_from_db(session_id: str) -> ChatMessageHistory:
  if session_id in store:
    history = store[session_id]
    if len(history.messages) > MAX_MESSAGES:
      history.messages = history.messages[-MAX_MESSAGES:]
    return history
  
  history = ChatMessageHistory()

  # ✅ Get latest MAX_MESSAGES, then reverse to chronological
  conversations = list(
      ChatConversations.objects.filter(
          session_id=session_id
      ).order_by('-created_at')[:MAX_MESSAGES]
  )[::-1]  # reverse to oldest → newest
  
  print(f"[DEBUG] conversations from DB: {len(conversations)}")

  for convo in conversations:
    history.add_user_message(convo.user_message)
    history.add_ai_message(convo.ai_message)

  store[session_id] = history
  return history

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

def conversation_chain(models, question, session_id="default"):
    if SYSTEM_PROMPTS == "":
      system_prompt = "You are a helpful and precise assistant for answering user queries."
    system_prompt = SYSTEM_PROMPTS

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
      
    runnable = RunnableWithMessageHistory(
       prompt | llm,
       # get_trimmed_session_history,
       load_history_from_db,
       input_messages_key="input",
       history_messages_key="history",
    )

    config = {"configurable": {"session_id": session_id}}
    lang_result = runnable.invoke({"input": question}, config=config)

    usage = {}
    if hasattr(lang_result, "response_metadata"):
        meta = lang_result.response_metadata
        usage = {
            "input_tokens": meta.get("prompt_eval_count", 0),
            "output_tokens": meta.get("eval_count", 0),
        }
    return lang_result.content, usage