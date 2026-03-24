# ollama_ai

A Django-based web chat application that connects to Ollama-compatible models, stores multi-session conversation history, and provides a sidebar-based chat experience.

## Features

- Real-time chat UI with session-based conversation history
- Multiple model selection (GLM, DeepSeek, Qwen, GPT-OSS, Nemotron, Minimax)
- Automatic chat title generation for new sessions
- Persistent storage of chat sessions and message history in SQLite
- Sidebar session list with "resume previous chat" behavior
- Markdown rendering for AI responses (code blocks, tables, fenced code)
- Django admin support for inspecting chat records

## Tech Stack

- Python 3.13+
- Django 6
- LangChain (`langchain`, `langchain-community`, `langchain-core`)
- Ollama Python client (`ollama`)
- SQLite (default DB)
- Frontend: server-rendered HTML/CSS/JS (no separate SPA build)

## Project Structure

```text
ollama_ai/
├── app/
│   ├── langchain.py         # LLM + memory orchestration
│   ├── models.py            # ChatSession and ChatConversations models
│   ├── ollama.py            # Ollama host/client + model mapping
│   ├── prompts.py           # System prompt text
│   ├── urls.py              # App routes
│   ├── views.py             # API and page handlers
│   └── migrations/          # Django migrations
├── ollama_ai/
│   ├── settings.py          # Django settings
│   └── urls.py              # Root URL configuration
├── templates/
│   └── chat.html            # Chat interface
├── requirements.txt
├── manage.py
└── db.sqlite3
```

## How It Works

1. Frontend loads `/` and renders `templates/chat.html`.
2. Existing sessions are fetched from `/chat/sessions/`.
3. When user sends a message:
   - If no `session_id`, server generates a title and creates a new `ChatSession`.
   - Server calls `conversation_chain()` in `app/langchain.py`.
   - AI response is saved into `ChatConversations`.
4. Session history is loaded from `/chat/history/<session_id>/`.
5. LangChain memory is loaded from DB and trimmed to `MAX_MESSAGES` per session.

## Prerequisites

- Python 3.13+ installed
- Network access to an Ollama-compatible host
- Valid API key for your Ollama host
- `pip` available in your Python environment

## Required Python Packages

Install everything from `requirements.txt`:

```bash
pip install -r requirements.txt
```

Main runtime dependencies used directly by this project:

- `Django`
- `langchain`, `langchain-community`, `langchain-core`
- `ollama`
- `python-dotenv`
- `Markdown`

Also present in `requirements.txt`:

- `langgraph*`, `langsmith`, `numpy`, `pillow`, `requests`, `gunicorn`

## Installation

1. Clone the project and move into the directory.
2. Create a virtual environment.
3. Install dependencies.
4. Configure environment variables.
5. Run migrations and start server.

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If you open a new terminal, activate the environment again before running Django commands:

```bash
source venv/bin/activate
```

## Environment Variables

Create a `.env` file in the project root:

```env
OLLAMA_API_KEY=your_api_key_here
OLLAMA_HOST=https://your-ollama-host
```

Used in:

- `app/ollama.py`
- `app/langchain.py`

## Database Setup

```bash
python3 manage.py makemigrations
python3 manage.py migrate
```

Optional admin user:

```bash
python3 manage.py createsuperuser
```

## Run Locally

```bash
python3 manage.py runserver
```

Open:

- App: `http://127.0.0.1:8000/`
- Admin: `http://127.0.0.1:8000/admin/`

## Verify Setup

Run these checks after installation:

```bash
python3 manage.py check
python3 manage.py test
```

## API Endpoints

- `GET /`
  - Render chat UI page.

- `POST /chat/`
  - Send a message.
  - Body fields:
    - `message` (string)
    - `model` (string key)
    - `session_id` (optional)
  - Returns:
    - `user_message`
    - `ai_message` (HTML rendered markdown)
    - `model`
    - `session_id`
    - `title`

- `GET /chat/history/<session_id>/`
  - Fetch full conversation history for one session.

- `GET /chat/sessions/`
  - Fetch all sessions for sidebar listing.

- `GET /chat/delete/<session_id>/`
  - Delete a session and its related conversations.

- `GET /chat/api/<session_id>/`
  - Returns one conversation item for the given session (legacy/debug route).

## Supported Model Keys

Defined in `app/ollama.py`:

- `glm-5` -> `glm-5:cloud`
- `glm-4.7` -> `glm-4.7:cloud`
- `gpt-oss` -> `gpt-oss:120b-cloud`
- `qwen3.5` -> `qwen3.5:397b-cloud`
- `deepseek-v3.2` -> `deepseek-v3.2:cloud`
- `deepseek-v3.1` -> `deepseek-v3.1:671b-cloud`
- `nemotron-3-super` -> `nemotron-3-super`
- `minimax-m2.7` -> `minimax-m2.7:cloud`

## Data Model

### `ChatSession`

- `id` (UUID-like string, primary key)
- `model`
- `title`
- `created_at`
- `updated_at`

### `ChatConversations`

- `id`
- `session` (FK -> `ChatSession`)
- `user_message`
- `ai_message`
- `created_at`
- `updated_at`

## Key Files You May Customize

- `app/prompts.py`: system prompt/persona behavior
- `app/ollama.py`: model mapping
- `app/langchain.py`: memory length (`MAX_MESSAGES`), chain behavior
- `templates/chat.html`: UI/UX and client-side interactions
- `ollama_ai/settings.py`: project settings, static/media, security

## Static and Media

- `STATIC_URL = 'static/'`
- `STATIC_ROOT = BASE_DIR/staticfiles`
- `MEDIA_URL = '/media/'`
- `MEDIA_ROOT = BASE_DIR/media`

During development (`DEBUG=True`), static and media routes are served by Django in `ollama_ai/urls.py`.

## Useful Commands

```bash
python3 manage.py runserver
python3 manage.py makemigrations
python3 manage.py migrate
python3 manage.py createsuperuser
python3 manage.py shell
python3 manage.py check
python3 manage.py test
```

## Troubleshooting

- `ModuleNotFoundError` (e.g., `markdown`):
  - Ensure virtual env is active and run `pip install -r requirements.txt`.
  - If it still fails, run `pip install Markdown` and re-run `python3 manage.py check`.
- Model request fails:
  - Verify `.env` values and API key validity.
  - Confirm `OLLAMA_HOST` is reachable.
- Empty/invalid chat response:
  - Check server logs for model key mismatch.

## Security Notes

- Current settings are development-oriented (`DEBUG=True`, permissive hosts).
- Move secrets out of source control and use environment-managed secrets.
- Rotate API keys if they were ever committed publicly.

## Deployment Notes

- `gunicorn` is included in `requirements.txt`.
- Suggested production steps:
  - Set `DEBUG=False`
  - Configure strict `ALLOWED_HOSTS`
  - Use a proper production database (PostgreSQL/MySQL) instead of SQLite
  - Serve static files via Nginx/CDN

## License

No explicit license file is currently present. Add a `LICENSE` file if you plan to share or distribute this project.
