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
    },
    {
        "key": "glm-4.7",
        "label": "GLM 4.7",
        "provider": "Zhipu",
        "model": "glm-4.7:cloud",
    },
    {
        "key": "gemini-3-flash-preview",
        "label": "Gemini 3 Flash Preview",
        "provider": "Google",
        "model": "gemini-3-flash-preview:cloud",
    },
    {
        "key": "gpt-oss",
        "label": "GPT OSS",
        "provider": "OpenAI",
        "model": "gpt-oss:120b-cloud",
    },
    {
        "key": "gemma3",
        "label": "Gemma 3",
        "provider": "Google",
        "model": "gemma3:27b-cloud",
    },
    {
        "key": "qwen3.5",
        "label": "Qwen 3.5",
        "provider": "Alibaba",
        "model": "qwen3.5:397b-cloud",
    },
    {
        "key": "kimi-k2.5",
        "label": "Kimi K2.5",
        "provider": "Moonshot",
        "model": "kimi-k2.5:cloud",
    },
    {
        "key": "deepseek-v3.2",
        "label": "DeepSeek V3.2",
        "provider": "DeepSeek",
        "model": "deepseek-v3.2:cloud",
    },
    {
        "key": "deepseek-v3.1",
        "label": "DeepSeek V3.1",
        "provider": "DeepSeek",
        "model": "deepseek-v3.1:671b-cloud",
    },
    {
        "key": "nemotron-3-super",
        "label": "Nemotron 3 Super",
        "provider": "NVIDIA",
        "model": "nemotron-3-super",
    },
    {
        "key": "minimax-m2.7",
        "label": "Minimax M2.7",
        "provider": "MiniMax",
        "model": "minimax-m2.7:cloud",
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
  return [{"key": item["key"], "label": item["label"], "provider": item["provider"]} for item in MODEL_CATALOG]

def conversations(model, message):
  client = ollama_client()
  response = client.chat(model=model, messages=[{'role': 'user', 'content': message}])
  return response['message']['content']
