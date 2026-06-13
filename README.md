# ChaliAssistant Backend

Django REST API for **ChaliAssistant** — a multi-tenant customer care platform where end customers chat, call, and send audio messages to an AI agent scoped to each company's knowledge base. Company staff manage tickets, follow-ups, knowledge, orders, media, and insights with strict tenant isolation.

## Architecture (3 apps)

| App | Responsibility |
|-----|----------------|
| **`accounts`** | Users, JWT auth, roles (customer, staff, platform admin) |
| **`tenants`** | Companies, staff memberships, AI config, knowledge base, permissions, middleware |
| **`operations`** | Conversations, messages, voice calls, tickets, orders, bookings, media library, insights, OpenAI services |

Tenant isolation is enforced via `company` foreign keys on all operational data and the `X-Company-ID` header for staff routes — not by splitting into many Django apps.

## Quick start

### 1. Install dependencies

```bash
cd chaliapp
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 2. Configure environment

Copy `.env.example` to `.env` and set your values:

```bash
copy .env.example .env
```

Required:

```env
SECRET_KEY=your-django-secret
OPENAI_API_KEY=sk-your-openai-key
ALLOWED_HOSTS=localhost,127.0.0.1,172.20.10.2
```

### 3. Migrate and seed demo data

```bash
python manage.py migrate
python manage.py bootstrap_demo
```

Demo accounts:

| Role | Email | Password |
|------|-------|----------|
| Platform admin | admin@chali.app | admin12345 |
| Company staff | staff@democompany.com | staff12345 |
| Customer | customer@example.com | customer12345 |

### 4. Run the server

Local only:

```bash
python manage.py runserver
```

Phone testing on same WiFi:

```bash
python manage.py runserver 0.0.0.0:8000
```

API base URL: `http://127.0.0.1:8000/api/`

Admin panel: `http://127.0.0.1:8000/admin/`

Health check: `http://127.0.0.1:8000/api/auth/health/`

---

## Authentication

Login with **email + password** (JWT):

```http
POST /api/auth/login/
Content-Type: application/json

{
  "email": "customer@example.com",
  "password": "customer12345"
}
```

Send on all authenticated requests:

```http
Authorization: Bearer <access_token>
```

Staff routes also require:

```http
X-Company-ID: 1
```

---

## API overview

### Public / customer

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/auth/health/` | Health check |
| POST | `/api/auth/register/` | Customer registration |
| POST | `/api/auth/login/` | JWT login |
| GET | `/api/companies/` | List active companies (logo URLs are absolute) |
| GET | `/api/conversations/` | Customer conversations |
| POST | `/api/conversations/{id}/messages/` | Text chat → AI reply |
| POST | `/api/conversations/{id}/messages/stream/` | Streaming AI reply (SSE) |
| POST | `/api/conversations/{id}/messages/audio/` | Audio message → AI audio reply |
| POST | `/api/conversations/{id}/voice-session/` | Mint OpenAI Realtime session |
| GET | `/api/my-tickets/` | Customer tickets |

### Staff (requires `Authorization` + `X-Company-ID`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/staff/my-companies/` | Companies this staff belongs to |
| GET/PATCH | `/api/staff/company/` | Company profile |
| GET/PATCH | `/api/staff/ai-config/` | ChaliAssistant AI settings |
| CRUD | `/api/staff/knowledge/` | Knowledge base documents |
| CRUD | `/api/staff/media/` | Company media library (images/files for AI sharing) |
| CRUD | `/api/staff/tickets/` | Tickets & follow-ups |
| GET | `/api/staff/insights/` | Dashboard metrics |
| CRUD | `/api/staff/orders/` | Orders (if enabled) |
| CRUD | `/api/staff/bookings/` | Bookings (if enabled) |

---

## Project structure

```
chaliapp/
├── accounts/           # Users & auth
├── tenants/            # Companies, KB, AI config, permissions
│   ├── models.py
│   ├── permissions.py
│   ├── middleware.py
│   ├── services.py     # KB search
│   └── views.py
├── operations/         # All customer-care operations
│   ├── models.py       # conversations, tickets, orders, media, ...
│   ├── views.py
│   ├── serializers.py
│   └── services/ai/    # OpenAI text, voice, audio
├── chalimobile/        # Django settings & root URLs
├── media/
├── requirements.txt
└── README.md
```

---

## OpenAI integration

- **Text / audio messages:** Django orchestrates OpenAI; mobile never holds the API key.
- **Voice calls:** Django mints ephemeral Realtime tokens; mobile connects directly to OpenAI WebRTC.

Configure per company in admin or via `PATCH /api/staff/ai-config/`.

---

## What to do next

1. Set `OPENAI_API_KEY` in `.env` and test a chat message.
2. Connect Flutter with `--dart-define=API_BASE_URL=http://<your-lan-ip>:8000`.
3. Re-upload company logo in admin if you reset the database.
4. Build the company portal against `/api/staff/*` endpoints.

---

Built for **ChaliAssistant** — AI-first customer care with human follow-through.
