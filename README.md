# ollama_ai

A Django-based web chat application that connects to Ollama-compatible models, stores multi-session conversation history, and provides a sidebar-based chat experience.

<img width="1364" height="649" alt="image" src="https://github.com/user-attachments/assets/9750bef1-2b4a-4552-8b10-60a8d944b395" />

<img width="1364" height="649" alt="image" src="https://github.com/user-attachments/assets/5a7ecd0e-d068-48fd-8da3-875975e8a92d" />


## Architecture Diagram
<img width="8192" height="1312" alt="Ollama Chat Interaction Flow-2026-03-25-175655" src="https://github.com/user-attachments/assets/0ba1d518-a948-483e-b1ef-002bc4fa73f1" />


## Features

- Real-time chat UI with session-based conversation history
- Multiple model selection (Gemini, Gemma, GLM, DeepSeek, Qwen, GPT-OSS, Nemotron, Minimax)
- Automatic chat title generation for new sessions
- Persistent storage of chat sessions and message history in PostgreSQL
- Sidebar session list with "resume previous chat" behavior
- Session deletion from sidebar (right-click / long-press)
- Markdown rendering for AI responses (code blocks, tables, fenced code)
- Django admin support for inspecting chat records
- Dynamic website settings (name, favicon, description) via database
- Maintenance mode middleware support
- Token usage tracking (`input_tokens`, `output_tokens`) per conversation
- Cloud usage panel (input/output/total tokens)
- Voice-to-text backend endpoint using Whisper (`faster-whisper`)

## Tech Stack

- Python 3.13+
- Django 6
- LangChain (`langchain`, `langchain-community`, `langchain-core`)
- Ollama Python client (`ollama`)
- PostgreSQL (via `DATABASE_URL`)
- Frontend: server-rendered HTML/CSS/JS (no separate SPA build)

## Project Structure

```text
ollama_ai/
├── app/
│   ├── langchain.py         # LLM + memory orchestration
│   ├── middlewares/         # Custom middleware
│   ├── models.py            # ChatSession and ChatConversations models
│   ├── ollama.py            # Ollama host/client + model mapping
│   ├── prompts.py           # System prompt text
│   ├── urls.py              # App routes
│   ├── views.py             # API and page handlers
│   ├── voice.py             # Voice-to-text endpoint (Whisper)
│   └── migrations/          # Django migrations
├── ollama_ai/
│   ├── settings.py          # Django settings
│   └── urls.py              # Root URL configuration
├── public/static/
│   ├── css/style.css        # Chat UI styles
│   ├── js/ollama.js         # Frontend chat logic
│   ├── js/delete-sessions.js # Session deletion handler
│   ├── js/usage.js          # Usage panel fetch logic
│   └── favicons/            # Uploaded favicon/media files
├── templates/
│   └── chat.html            # Main chat interface
├── requirements.txt
├── manage.py
└── README.md
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
- PostgreSQL server (local or remote)
- Network access to an Ollama-compatible host
- Valid API key for your Ollama host
- `pip` available in your Python environment
- Modern browser (Chrome/Edge recommended for SpeechRecognition support)

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
- `psycopg2-binary`
- `pillow`
- `faster-whisper`

Also present in `requirements.txt`:

- `langgraph*`, `langsmith`, `numpy`, `requests`, `gunicorn`

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
DATABASE_URL=postgresql://username:password@host:5432/database_name
```

Used in:

- `app/ollama.py`
- `app/langchain.py`
- `ollama_ai/settings.py`

## Browser Requirements

- Voice UI controls are present in the frontend.
- Server-side transcription is handled by the `/chat/voice/` endpoint with Whisper.

## Database Setup (PostgreSQL)

The current settings are configured for PostgreSQL using `DATABASE_URL`.

Example URL formats:

```env
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/ollama_ai
DATABASE_URL=postgres://postgres:postgres@127.0.0.1:5432/ollama_ai
```

After DB config is ready, run:

```bash
python3 manage.py makemigrations
python3 manage.py migrate
```

Optional admin user:

```bash
python3 manage.py createsuperuser
```

Then login at `/admin/` and configure `WebsiteSettings` (site name, description, favicon, maintenance mode) if needed.

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
    - `model_key`
    - `session_id`
    - `title`
    - `input_tokens`
    - `output_tokens`
    - `total_tokens`

- `POST /chat/voice/`
  - Accepts uploaded audio file (`audio`) and returns transcribed text:
    - `text`

- `GET /chat/history/<session_id>/`
  - Fetch full conversation history for one session.

- `GET /chat/sessions/`
  - Fetch all sessions for sidebar listing.

- `GET /chat/delete/<session_id>/`
  - Delete a session and its related conversations.

- `GET /chat/api/<session_id>/`
  - Returns one conversation item for the given session (legacy/debug route).

- `GET /api/usage-stats/`
  - Returns aggregated usage:
    - `total_input_tokens`
    - `total_output_tokens`
    - `total_tokens`
    - `total_conversations`

## Supported Model Keys

Defined in `app/ollama.py`:

- `gemini-3-flash-preview` -> `gemini-3-flash-preview:cloud`
- `gemma3` -> `gemma3:27b-cloud`
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
- `input_tokens`
- `output_tokens`
- `created_at`
- `updated_at`

### `WebsiteSettings`

- `website_name`
- `website_logo`
- `website_favicon`
- `website_description`
- `maintainance_mode`

## Key Files You May Customize

- `app/prompts.py`: system prompt/persona behavior
- `app/ollama.py`: model mapping
- `app/langchain.py`: memory length (`MAX_MESSAGES`), chain behavior
- `app/voice.py`: Whisper-based speech-to-text handling
- `app/middlewares/constructions.py`: maintenance mode behavior
- `app/utils.py`: website settings context processor
- `public/static/js/ollama.js`: chat frontend interactions and session model lock
- `public/static/js/delete-sessions.js`: sidebar delete action handlers
- `public/static/js/usage.js`: usage dashboard fetch/format logic
- `public/static/css/style.css`: visual theme/layout
- `templates/chat.html`: UI/UX and client-side interactions
- `ollama_ai/settings.py`: project settings, static/media, security

## Static and Media

- `STATIC_URL = '/static/'`
- `STATIC_ROOT = BASE_DIR/staticfiles`
- `MEDIA_URL = '/media/'` (used for frontend CSS/JS and uploaded media in current setup)
- `MEDIA_ROOT = BASE_DIR/public/static`

During development (`DEBUG=True`), media routes are served by Django in `ollama_ai/urls.py`, and static URLs are added via `staticfiles_urlpatterns()`.

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

- `ModuleNotFoundError: No module named 'dotenv'`:
  - Install project requirements: `pip install -r requirements.txt`
  - Ensure virtual environment is activated before running Django commands.
- `ModuleNotFoundError` (e.g., `markdown`):
  - Ensure virtual env is active and run `pip install -r requirements.txt`.
  - If it still fails, run `pip install Markdown` and re-run `python3 manage.py check`.
- Database config errors (`DATABASE_URL` missing/invalid):
  - Add `DATABASE_URL` in `.env` (PostgreSQL connection string).
  - Ensure PostgreSQL is reachable with those credentials.
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
  - Keep PostgreSQL credentials in environment variables only
  - Serve static files via Nginx/CDN

## License

No explicit license file is currently present. Add a `LICENSE` file if you plan to share or distribute this project.
