from ollama import Client
from dotenv import load_dotenv
import os
load_dotenv()

MODEL_CATALOG = [
    {
        "key": "glm-5",
        "label": "GLM 5",
        "provider": "Zhipu",
        "model": "glm-5:cloud",
        "supports_documents": True,
        "supports_vision": False,
    },
    {
        "key": "glm-4.7",
        "label": "GLM 4.7",
        "provider": "Zhipu",
        "model": "glm-4.7:cloud",
        "supports_documents": False,
        "supports_vision": False,
    },
    {
        "key": "gemini-3-flash-preview",
        "label": "Gemini 3 Flash Preview",
        "provider": "Google",
        "model": "gemini-3-flash-preview:cloud",
        "supports_documents": True,
        "supports_vision": True,
    },
    {
        "key": "gpt-oss",
        "label": "GPT OSS",
        "provider": "OpenAI",
        "model": "gpt-oss:120b-cloud",
        "supports_documents": True,
        "supports_vision": False,
    },
    {
        "key": "gemma3",
        "label": "Gemma 3",
        "provider": "Google",
        "model": "gemma3:27b-cloud",
        "supports_documents": False,
        "supports_vision": True,
    },
    {
        "key": "gemma4",
        "label": "Gemma 4",
        "provider": "Google",
        "model": "gemma4:31b-cloud",
        "supports_documents": True,
        "supports_vision": True,
    },
    {
        "key": "qwen3.5",
        "label": "Qwen 3.5",
        "provider": "Alibaba",
        "model": "qwen3.5:397b-cloud",
        "supports_documents": True,
        "supports_vision": True,
    },
    {
        "key": "qwen3-vl",
        "label": "Qwen 3 VL",
        "provider": "Alibaba",
        "model": "qwen3-vl:235b-cloud",
        "supports_documents": True,
        "supports_vision": True,
    },
    {
        "key": "kimi-k2.5",
        "label": "Kimi K2.5",
        "provider": "Moonshot",
        "model": "kimi-k2.5:cloud",
        "supports_documents": True,
        "supports_vision": True,
    },
    {
        "key": "deepseek-v3.2",
        "label": "DeepSeek V3.2",
        "provider": "DeepSeek",
        "model": "deepseek-v3.2:cloud",
        "supports_documents": True,
        "supports_vision": False,
    },
    {
        "key": "deepseek-v3.1",
        "label": "DeepSeek V3.1",
        "provider": "DeepSeek",
        "model": "deepseek-v3.1:671b-cloud",
        "supports_documents": True,
        "supports_vision": False,
    },
    {
        "key": "nemotron-3-super",
        "label": "Nemotron 3 Super",
        "provider": "NVIDIA",
        "model": "nemotron-3-super",
        "supports_documents": False,
        "supports_vision": False,
    },
    {
        "key": "minimax-m2.7",
        "label": "Minimax M2.7",
        "provider": "MiniMax",
        "model": "minimax-m2.7:cloud",
        "supports_documents": False,
        "supports_vision": False,
    },
]

MODEL_MAP = {item["key"]: item["model"] for item in MODEL_CATALOG}

def ollama_client():
  return Client(
    host=os.getenv("OLLAMA_HOST"), 
    headers={'Authorization': 'Bearer ' + os.getenv("OLLAMA_API_KEY")}
  )

def load_models(model):
  return MODEL_MAP[model]

def list_models():
  return [
    {
      "key": item["key"],
      "label": item["label"],
      "provider": item["provider"],
      "supports_documents": item.get("supports_documents", False),
      "supports_vision": item.get("supports_vision", False),
    }
    for item in MODEL_CATALOG
  ]

def supports_documents(model_key):
  for item in MODEL_CATALOG:
    if item["key"] == model_key:
      return bool(item.get("supports_documents"))
  return False

def supports_vision(model_key):
  for item in MODEL_CATALOG:
    if item["key"] == model_key:
      return bool(item.get("supports_vision"))
  return False

def conversations(model, message):
  client = ollama_client()
  response = client.chat(model=model, messages=[{'role': 'user', 'content': message}])
  return response['message']['content']
