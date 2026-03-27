from ollama import Client
from dotenv import load_dotenv
import os
load_dotenv()

def ollama_client():
  return Client(
    host=os.getenv("OLLAMA_HOST"), 
    headers={'Authorization': 'Bearer ' + os.getenv("OLLAMA_API_KEY")}
  )

def load_models(model):
  OLLAMA_MODELS = {
    'gemini-3-flash-preview': 'gemini-3-flash-preview:cloud',
    'gemma3': 'gemma3:27b-cloud',
    'glm-4.7': 'glm-4.7:cloud',
    'nemotron-3-super': 'nemotron-3-super',
    'glm-5': 'glm-5:cloud',
    'deepseek-v3.2': 'deepseek-v3.2:cloud',
    'gpt-oss': 'gpt-oss:120b-cloud',
    'deepseek-v3.1': 'deepseek-v3.1:671b-cloud',
    'qwen3.5': 'qwen3.5:397b-cloud',
    'minimax-m2.7': 'minimax-m2.7:cloud',
  }
  return OLLAMA_MODELS[model]

def conversations(model, message):
  client = ollama_client()
  response = client.chat(model=model, messages=[{'role': 'user', 'content': message}])
  return response['message']['content']