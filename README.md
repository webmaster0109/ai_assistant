# ollama_ai

A full-stack AI chat app with a Django backend and React frontend, built for Ollama-compatible models with authentication, per-user sessions, token tracking, PDF document chat, streaming responses, and public share links.

## Project Layout

- `backend/` -> Django app, APIs, models, migrations, templates, static/media
- `frontend/` -> React + Vite client
- root -> Docker and repo-level files

## Features

- User registration/login/logout (username or email login)
- Per-user chat sessions with ownership checks
- Model catalog API with document-capability flags
- Standard chat and streaming chat (SSE)
- Stop active streaming generation
- Edit message + regenerate assistant response
- Pin chats (max 3 pinned per user)
- Public/private chat sharing with tokenized link
- PDF upload + chunk extraction + context-aware document chat
- Session-scoped document selection
- Usage stats overall and per model
- Dynamic branding + system prompt from `WebsiteSettings`
- Redis-backed history cache (with local-memory fallback)

## Tech Stack

- Backend: Django 6, Gunicorn
- AI: LangChain + `langchain-ollama`
- LLM transport: `ollama` Python client
- Document parsing: `pypdf` (via `PyPDFLoader`)
- Frontend: React 19 + Vite 7
- DB: PostgreSQL via `DATABASE_URL` (SQLite fallback)
- Cache: Redis via `django-redis` (`LocMemCache` fallback)

## Requirements

- Python 3.11+ (Docker uses Python 3.11)
- Node.js 22+ (for frontend local build/dev)
- Ollama-compatible host + API key
- PostgreSQL + Redis recommended for production

Install backend dependencies:

```bash
pip install -r backend/requirements.txt
```

Install frontend dependencies:

```bash
cd frontend
npm install
```

## Environment Variables

Create `.env` at repo root:

```env
OLLAMA_HOST=https://your-ollama-host
OLLAMA_API_KEY=your_api_key
DATABASE_URL=postgresql://user:password@host:5432/dbname
REDIS_URL=redis://127.0.0.1:6379/1
CSRF_TRUSTED_ORIGINS=https://your-domain.com,https://www.your-domain.com
```

Notes:

- If `DATABASE_URL` is missing, SQLite is used (`backend/db.sqlite3`).
- If `REDIS_URL` is missing, local-memory cache is used.
- Current DB URL config enables SSL when `DATABASE_URL` is set.

## Local Run

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt
cd backend
python manage.py migrate
python manage.py runserver
```

App URLs:

- App: `http://127.0.0.1:8000/`
- Admin: `http://127.0.0.1:8000/admin/`

Optional admin user:

```bash
cd backend
python manage.py createsuperuser
```

## Frontend Dev

```bash
cd frontend
npm install
npm run dev
```

Build frontend bundle for Django:

```bash
cd frontend
npm run build
```

Built assets are served from `backend/static/frontend/`.

## Docker

```bash
docker compose up --build
```

Startup behavior:

- `backend/entrypoint.sh` runs `python manage.py migrate --noinput`
- then Gunicorn starts

Migration guidance:

- Keep `migrate` in runtime entrypoint
- Keep `makemigrations` manual in development and commit migration files

## API Endpoints

### App + PWA

- `GET /` -> app shell
- `GET /share/<share_token>/` -> shared app shell route
- `GET /sw.js` -> service worker
- `GET /manifest.webmanifest` -> web manifest

### Auth

- `GET /api/auth/me/`
- `POST /api/auth/register/`
- `POST /api/auth/login/`
- `POST /api/auth/logout/`

### Models

- `GET /api/models/`

### Chat (Auth Required)

- `POST /api/chat/`
- `POST /api/chat/stream/`
- `POST /api/chat/streams/<stream_id>/stop/`
- `GET /api/chat/sessions/`
- `DELETE /api/chat/sessions/<session_id>/`
- `POST /api/chat/sessions/<session_id>/pin/`
- `POST /api/chat/sessions/<session_id>/share/`
- `GET /api/chat/sessions/<session_id>/messages/`
- `POST /api/chat/sessions/<session_id>/messages/<conversation_id>/edit/`
- `POST /api/chat/sessions/<session_id>/messages/<conversation_id>/regenerate/`

### Documents (Auth Required)

- `POST /api/chat/documents/` -> upload PDF and attach to chat
- `POST /api/chat/sessions/<session_id>/documents/<document_id>/select/` -> switch active document

### Usage + Public Share

- `GET /api/usage-stats/`
- `GET /api/usage-stats/models/`
- `GET /api/public/chat/<share_token>/`

## Supported Model Keys

From `backend/app/ollama.py`:

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

Some models are flagged with `supports_documents=true` for PDF chat.

## Core Data Models

- `ChatSession`: owner, model, title, pinned/public/share fields, timestamps
- `ChatConversations`: session, user/assistant messages, token counts, timestamps
- `ChatDocument`: uploaded PDF metadata + active flag + extracted character count
- `ChatDocumentChunk`: chunked document content with page metadata
- `WebsiteSettings`: branding, maintenance mode, system prompt

## Useful Commands

```bash
cd backend
python manage.py check
python manage.py test
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

## Notes

- Legacy files like `backend/templates/chat.html` and `backend/public/static/js/*` still exist, but current app shell uses `backend/templates/app.html` + built frontend assets.
- `backend/app/voice.py` and `backend/app/streaming.py` exist, but main routes are served from `backend/app/views.py` endpoints listed above.
- Current settings are development-friendly (`DEBUG=True`, permissive hosts). Harden before production.
