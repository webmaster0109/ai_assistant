import base64
from pathlib import Path
from .ollama import is_vision_model, load_models

def encode_image(image_path: str) -> str:
  with open(image_path, 'rb') as f:
    return base64.b64encode(f.read()).decode('utf-8')

def get_image_mime(image_path: str) -> str:
  ext = Path(image_path).suffix.lower()
  return {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
  }.get(ext, 'image/jpeg')