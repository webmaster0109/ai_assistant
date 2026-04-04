# ollama_ai

A Django + React chat application for Ollama-compatible hosted models, with authentication, per-user session history, token usage tracking, and dynamic site branding from Django admin.

## Features

- Email/username login and registration
- Per-user chat sessions (users can only access their own sessions)
- Model catalog API and model selection for new chats
- Automatic chat title generation for new sessions
- Conversation persistence in DB with token accounting
- Usage stats API scoped to the authenticated user
- Redis-backed chat history caching (with local-memory fallback)
- Dynamic branding and system prompt via `WebsiteSettings`
- Admin panel for sessions, conversations, and website settings
- Dockerized backend + PostgreSQL + Redis setup
- Vite/React frontend bundled into Django static files

## Tech Stack

- Backend: Django 6, Gunicorn
- AI orchestration: LangChain + `langchain-ollama`
- LLM transport: `ollama` Python client
- Frontend: React 19 + Vite 7
- Database: PostgreSQL via `DATABASE_URL` (SQLite fallback)
- Cache: Redis via `django-redis` (`LocMemCache` fallback)

## Requirements

- Python 3.11+ (Docker image uses Python 3.11)
- Node.js 22+ (only needed when building frontend locally)
- An Ollama-compatible endpoint and API key
- PostgreSQL and Redis (recommended for production)

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Install frontend dependencies (if you want to run/build frontend manually):

```bash
cd frontend
npm install
```

## Environment Variables

Create a `.env` in project root:

```env
OLLAMA_HOST=https://your-ollama-host
OLLAMA_API_KEY=your_api_key
DATABASE_URL=postgresql://user:password@host:5432/dbname
REDIS_URL=redis://127.0.0.1:6379/1
CSRF_TRUSTED_ORIGINS=https://your-domain.com,https://www.your-domain.com
```

Notes:

- `DATABASE_URL` is optional. If omitted, SQLite (`db.sqlite3`) is used.
- If `REDIS_URL` is omitted, Django uses local memory cache.
- Current DB config sets `ssl_require=True` when `DATABASE_URL` is present.

## Run Locally (Without Docker)

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open:

- App: `http://127.0.0.1:8000/`
- Admin: `http://127.0.0.1:8000/admin/`

Optional admin user:

```bash
python manage.py createsuperuser
```

## Frontend Development

Run Vite dev server:

```bash
cd frontend
npm install
npm run dev
```

Build frontend assets for Django:

```bash
cd frontend
npm run build
```

Built files are served from `static/frontend/assets/*` via Django staticfiles.

## Docker

Build and start services:

```bash
docker compose up --build
```

What happens on container start:

- `entrypoint.sh` runs `python manage.py migrate --noinput`
- Then Gunicorn starts

Important:

- Keep `migrate` in entrypoint/runtime, not Docker image build stage.
- `makemigrations` should not be auto-run in Docker startup. Create migrations explicitly during development and commit them.

## API Endpoints

### Public/Auth

- `GET /` -> serve `templates/app.html`
- `GET /api/auth/me/` -> auth status + branding
- `POST /api/auth/register/`
- `POST /api/auth/login/`
- `POST /api/auth/logout/`
- `GET /api/models/` -> available model keys/labels/providers

### Auth Required

- `GET /api/chat/sessions/` -> list user sessions
- `GET /api/chat/sessions/<session_id>/messages/` -> session + messages
- `POST /api/chat/` -> send chat message
- `DELETE /api/chat/sessions/<session_id>/` -> delete session
- `GET /api/usage-stats/` -> user token stats

### Chat Request/Response

`POST /api/chat/` body:

```json
{
  "message": "Explain Django middleware",
  "model": "glm-5",
  "session_id": "optional-existing-session-id"
}
```

Response shape:

```json
{
  "session": {
    "id": "...",
    "title": "...",
    "model": "glm-5",
    "created_at": "...",
    "updated_at": "...",
    "preview": "..."
  },
  "message": {
    "id": 1,
    "user_message": "...",
    "ai_message": "...",
    "input_tokens": 123,
    "output_tokens": 456,
    "created_at": "..."
  },
  "usage": {
    "input_tokens": 123,
    "output_tokens": 456,
    "total_tokens": 579
  }
}
```

## Supported Model Keys

Defined in `app/ollama.py`:

- `glm-5`
- `glm-4.7`
- `gemini-3-flash-preview`
- `gpt-oss`
- `gemma3`
- `qwen3.5`
- `kimi-k2.5`
- `deepseek-v3.2`
- `deepseek-v3.1`
- `nemotron-3-super`
- `minimax-m2.7`

## Data Model

### `ChatSession`

- `id` (custom UUID-like string, primary key)
- `owner` (FK to Django user)
- `model`
- `title`
- `created_at`
- `updated_at`

### `ChatConversations`

- `session` (FK to `ChatSession`)
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
- `system_prompt`
- `maintainance_mode`

## Project Structure

```text
ollama_ai/
├── app/
│   ├── admin.py
│   ├── langchain.py
│   ├── middlewares/
│   ├── migrations/
│   ├── models.py
│   ├── ollama.py
│   ├── streaming.py
│   ├── urls.py
│   ├── utils.py
│   ├── views.py
│   └── voice.py
├── frontend/
│   ├── src/
│   ├── package.json
│   └── vite.config.js
├── ollama_ai/
│   ├── settings.py
│   └── urls.py
├── public/static/
│   ├── css/
│   ├── favicons/
│   └── js/
├── static/frontend/
├── templates/
│   ├── app.html
│   └── chat.html
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── requirements.txt
└── manage.py
```

## Useful Commands

```bash
python manage.py check
python manage.py test
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

## Notes

- `templates/chat.html` and files under `public/static/js/*` are present, but current root route serves `templates/app.html`.
- `app/voice.py` and `app/streaming.py` are not currently wired in `app/urls.py`.
- If you enable production mode, tighten `ALLOWED_HOSTS`, set secure CSRF origins, and move secrets to environment-managed storage.
