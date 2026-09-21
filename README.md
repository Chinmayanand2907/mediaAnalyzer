# EngageIQ — Social Media Engagement Analyzer

<div align="center">
  <h3>Ingest · Analyze · Predict · Chat</h3>
  <p>A full-stack analytics platform that bridges YouTube and Reddit data with NLP sentiment analysis, XGBoost-powered engagement forecasting, and a context-aware AI analyst chatbot.</p>
</div>

---

## Overview

**EngageIQ** is an end-to-end social media intelligence platform. It fetches raw data from YouTube and Reddit via their official APIs, stores it across a dual-database layer (MongoDB for raw payloads, PostgreSQL for structured metrics), runs HuggingFace RoBERTa sentiment analysis and XGBoost engagement forecasting in the background via Celery, and exposes everything through a FastAPI REST layer to a React dashboard — complete with a live AI analyst chatbot powered by Google Gemini (gemini-2.5-flash-lite).

---

## Features

### Data Ingestion
- **YouTube** — syncs channel metadata, individual video stats (views, likes, comments, publish timestamps), and top audience comments via YouTube Data API v3.
- **Reddit** — scrapes subreddit posts, upvote ratios, comment trees, and community activity via PRAW.
- **Asynchronous pipeline** — all heavy ingestion and processing runs in the background via **Celery** workers with **Redis** as the message broker, keeping the API fully non-blocking.
- Dedicated Celery queues: `celery` (default), `youtube`, `reddit` — with explicit **task routing** so YouTube and Reddit ingestion are dispatched to their own queues automatically.
- **Bulk comment writes** — YouTube comment ingestion now uses MongoDB `bulk_write` with `ordered=False` for significantly faster data loading.
- **Accurate video-level statistics** — likes and comment counts are now aggregated per-video (not per-comment), removing the previous double-counting bug.

### Sentiment Analysis
- Primary engine: **`cardiffnlp/twitter-roberta-base-sentiment-latest`** (HuggingFace Transformers) — a RoBERTa model fine-tuned on social media text.
- Automatic fallback to **NLTK VADER** when the transformer model cannot be loaded (e.g., cold-start without GPU).
- All sentiment inference inside async FastAPI route handlers is run via `asyncio.to_thread` to avoid blocking the event loop.
- Produces **positive / neutral / negative** distribution scores persisted into PostgreSQL per account.
- Unknown future model labels now default to `neutral` instead of `negative` to avoid classification bias.

### Engagement Prediction
- **XGBoost regression model** trained on historical engagement features: view counts, like/comment ratios, publish hour/day-of-week, lag metrics, and sentiment scores.
- Multi-step **iterative forecasting** for the next N posts.
- Graceful fallback to a **moving-average baseline** when XGBoost is unavailable (e.g., missing `libomp` on macOS).
- In-process training helper for model creation or periodic re-training (`train_xgboost.py`).

### Cross-Platform Analytics
- **Shared video discovery** — scans Reddit comments for YouTube URLs, enriches matches with metadata, propagation delay, and audience sentiment from both platforms.
- **Sentiment comparison** — side-by-side positive/neutral/negative breakdown for the same content across YouTube and Reddit.
- **Topic correlation** — keyword and topic extraction from both platforms to surface overlapping discussion themes.
- **Normalized engagement index** (0–100) enabling like-for-like comparison between YouTube channels and Reddit communities. The Reddit scoring formula now blends audience reach (50%) with discussion intensity (50%) and correctly handles subreddit snapshots without comment data.
- **Subreddit filtering** — all cross-platform queries now use case-insensitive MongoDB regex matching for `parent_id`, preventing missed results due to capitalisation differences.
- **Correlation summary** — single unified payload combining shared videos, engagement, sentiment, and topics.

### Semantic Matching
- Cross-platform content similarity powered by **Sentence-BERT** (`all-MiniLM-L6-v2`), with configurable cosine similarity threshold (`SEMANTIC_SIMILARITY_THRESHOLD`).
- **Persistent TF-IDF fallback** — when SentenceTransformer is unavailable, a single `TfidfVectorizer` instance is reused across encode calls so YouTube and Reddit embeddings share the same feature space, making cosine similarity meaningful. Vocabulary is refitted automatically on mismatch and can be reset via `reset_fallback()`.

### AI Analyst Chatbot
- Powered by **Google Gemini (gemini-2.5-flash-lite)** via the OpenAI-compatible API.
- Context is **dynamically injected at request time** — the backend fetches live metrics from MongoDB and PostgreSQL and embeds them into the system prompt before calling the LLM.
- Three specialist personas depending on active dashboard view:
  - `youtube` → **Video Performance Consultant**
  - `reddit` → **Community Management Specialist**
  - `cross-platform` → **Cross-Channel Strategist**
- Answers are grounded exclusively in real data; the model is explicitly prevented from hallucinating metrics.

### Interactive Dashboard (React 19 + Vite)
- Upgraded to **React 19** and **React DOM 19**.
- **YouTube View** — channel KPIs, per-video timeline, sentiment pie, keyword frequency bar chart, and comment table.
- **Reddit View** — subreddit stats (members, active users, posts/comments), sentiment distribution, trending keywords, and raw comment feed.
- **Cross-Platform View** — redesigned with a **tabbed search control** (Analyze a Video / Explore a Subreddit), dedicated YouTube Reach and Viral Latency stat cards, live-dot subreddit indicator, and a shared videos table with normalized Reddit permalink resolution.
- **ChatBot Panel** — floating chat window with context awareness based on the active view.
- Client-side in-memory analytics cache (`useAnalytics` hook) to avoid redundant API calls.
- Vite dev server now binds to all interfaces (`host: true`, `strictPort: true`) and accepts `VITE_API_TARGET` to override the backend proxy target (useful for Docker vs. local dev).

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | React 19, Vite, Recharts, Lucide React, Tailwind CSS v4 |
| **Backend API** | FastAPI 0.115, Uvicorn, Python 3.12+ |
| **Task Queue** | Celery 5.5, Redis 7 |
| **ORM / Validation** | SQLModel, SQLAlchemy 2 (async, `async_sessionmaker`), Pydantic v2 |
| **Databases** | PostgreSQL 17 (structured metrics), MongoDB Atlas (raw payloads & comments) |
| **ML / NLP** | HuggingFace Transformers (RoBERTa), NLTK VADER, XGBoost, Scikit-learn, Pandas, NumPy |
| **Semantic Matching** | Sentence-BERT (`all-MiniLM-L6-v2`), TF-IDF fallback |
| **LLM / Chatbot** | Google Gemini (gemini-2.5-flash-lite), OpenAI-compatible SDK |
| **External APIs** | YouTube Data API v3 (`google-api-python-client`), Reddit API (`PRAW 8`) |
| **DevOps** | Docker, Docker Compose (5-service stack) |
| **Testing** | Pytest, pytest-asyncio, pytest-mock, mongomock-motor, aiosqlite |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    React 19 + Vite                   │
│  YouTube View │ Reddit View │ Cross-Platform │ Chat  │
└────────────────────────┬────────────────────────────┘
                         │ HTTP (REST) / Vite Proxy
┌────────────────────────▼────────────────────────────┐
│                    FastAPI (Uvicorn)                  │
│  /api/v1/youtube  /reddit  /cross-platform  /chatbot │
└──────┬──────────────────────────────────┬───────────┘
       │ enqueue tasks                    │ query data
┌──────▼──────┐                  ┌────────▼──────────┐
│    Redis    │                  │   PostgreSQL 17    │
│  (broker +  │                  │  structured KPIs,  │
│   results + │                  │  sentiment scores  │
│ rate-limit) │                  └────────────────────┘
└──────┬──────┘                           ▲
       │ consume (routed queues)          │ write processed
┌──────▼──────────────────┐              │
│   Celery Workers        │──────────────┘
│  youtube / reddit queues│
│  sentiment (RoBERTa)    │──► MongoDB Atlas
│  prediction (XGBoost)   │     (raw payloads,
└──────────┬──────────────┘      comments)
           │ fetch raw data
   ┌───────┴────────┐
   │ YouTube API v3 │  Reddit API (PRAW)
   └────────────────┘
```

---

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) & Docker Compose v2
- A **MongoDB Atlas** cluster (free tier works) — or any reachable MongoDB URI
- API credentials (see Environment Setup below)

---

### 1. Clone & Configure

```bash
git clone https://github.com/Chinmayanand2907/mediaAnalyzer.git
cd mediaAnalyzer

cp .env.example .env
```

Open `.env` and fill in your credentials:

| Variable | Where to get it |
|---|---|
| `POSTGRES_PASSWORD` | Choose any password (Docker will use it) |
| `MONGO_URI` | MongoDB Atlas → Connect → Drivers |
| `YOUTUBE_API_KEY` | [Google Cloud Console](https://console.cloud.google.com/) → YouTube Data API v3 |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | [Reddit App Preferences](https://www.reddit.com/prefs/apps) → create a script app |
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) |

---

### 2. Run with Docker (Recommended)

This starts all five services — PostgreSQL, Redis, FastAPI backend, Celery worker, and Vite frontend — with a single command:

```bash
docker compose up -d --build
```

| Service | URL |
|---|---|
| 🖥️ Frontend Dashboard | http://localhost:5173 |
| ⚙️ Backend API | http://localhost:8000 |
| 📖 Swagger / OpenAPI Docs | http://localhost:8000/docs |
| 🗄️ PostgreSQL | localhost:5432 |
| 🔄 Redis | localhost:6379 |

To stop everything:

```bash
docker compose down
```

---

### 3. Local Development (Without Docker)

Requires local PostgreSQL, Redis, and MongoDB to be running. Use the helper scripts to manage PostgreSQL and Redis:

```bash
# Start PostgreSQL and Redis (uses DBngin on macOS by default)
./start_dbs.sh

# Stop them when done
./stop_dbs.sh
```

> The scripts use a **PID file** (`/tmp/engageiq-redis.pid`) to reliably stop Redis without touching other processes on port 6379. You can override the paths via environment variables: `PG_CTL`, `PGDATA`, `REDIS_SERVER`, `REDIS_CLI`, `REDIS_DIR`, `REDIS_PIDFILE`.

#### Backend

Open **two terminal tabs** in the project root:

```bash
# Both terminals — activate the virtualenv first
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Terminal 1 — FastAPI
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — Celery worker
celery -A app.core.celery_app worker --loglevel=info -Q celery,youtube,reddit
```

> **macOS note:** XGBoost requires OpenMP. If you see a prediction fallback warning, run `brew install libomp` and restart the process.

#### Frontend

```bash
cd frontend
npm install
npm run dev
```

> To point the frontend proxy at a different backend (e.g. a remote staging host), set `VITE_API_TARGET` before running:
> ```bash
> VITE_API_TARGET=http://staging.example.com:8000 npm run dev
> ```

---

## Project Structure

```
mediaAnalyzer/
│
├── app/                          # FastAPI backend
│   ├── api/v1/routers/
│   │   ├── youtube.py            # /api/v1/youtube — sync, metrics, sentiment
│   │   ├── reddit.py             # /api/v1/reddit  — sync, sentiment, keywords
│   │   ├── cross_platform.py     # /api/v1/cross-platform — correlation & comparison
│   │   └── chatbot.py            # /api/v1/chatbot — Google Gemini LLM with live data context
│   ├── core/
│   │   ├── config.py             # Pydantic Settings (env vars, DSNs, quota limits)
│   │   ├── celery_app.py         # Celery instance, queue definitions & task routing
│   │   ├── cache.py              # Redis async cache (loop-safe singleton)
│   │   └── rate_limiter.py       # Token-bucket rate limiter (Redis Lua + in-memory fallback)
│   ├── db/
│   │   ├── postgres.py           # SQLAlchemy async engine, async_sessionmaker, ORM models
│   │   └── mongodb.py            # Motor async client, collection helpers, compound indexes
│   ├── models/                   # SQLModel table definitions
│   ├── schemas/                  # Pydantic request/response schemas
│   ├── services/
│   │   ├── analytics/
│   │   │   ├── sentiment_service.py   # RoBERTa + VADER sentiment engine (CPU, thread-safe)
│   │   │   ├── prediction_engine.py   # XGBoost forecasting + MA fallback
│   │   │   ├── semantic_matcher.py    # Sentence-BERT / TF-IDF cross-platform matcher
│   │   │   └── train_xgboost.py       # Training helper script
│   │   └── external/
│   │       ├── youtube_client.py      # YouTube Data API v3 wrapper
│   │       └── reddit_client.py       # PRAW Reddit API wrapper
│   ├── tasks/
│   │   └── ingestion_tasks.py    # Celery tasks: ingest (bulk write), sentiment, prediction
│   └── main.py                   # FastAPI app factory & lifespan hooks
│
├── frontend/                     # React 19 + Vite dashboard
│   └── src/
│       ├── api/client.js         # Axios API wrappers
│       ├── components/
│       │   ├── charts/           # Recharts components (sentiment, engagement, topics)
│       │   ├── layout/           # Navbar, StatCard
│       │   ├── tables/           # CommentsTable, SharedVideosTable
│       │   └── ChatBotPanel.jsx  # AI chatbot UI
│       ├── hooks/useAnalytics.js # In-memory caching hook
│       ├── pages/Dashboard.jsx   # Root page / layout shell
│       └── views/
│           ├── YoutubeView.jsx
│           ├── RedditView.jsx
│           └── CrossPlatformView.jsx   # Tabbed search, reach & latency cards
│
├── tests/                        # Pytest suite
│   ├── conftest.py               # Shared fixtures (mongomock-motor, aiosqlite)
│   ├── test_routers.py
│   ├── test_clients.py
│   ├── test_db.py
│   └── test_tasks.py
│
├── Dockerfile                    # Multi-stage build (builder → runtime)
├── docker-compose.yml            # 5-service orchestration
├── requirements.txt
├── .env.example                  # Environment variable template
├── start_dbs.sh                  # Local dev: start PostgreSQL + Redis (PID-file aware)
├── stop_dbs.sh                   # Local dev: stop PostgreSQL + Redis (PID-file aware)
└── pytest.ini
```

---

## Running Tests

```bash
# From the project root with .venv active
pytest -v
```

The test suite uses `mongomock-motor` for an in-memory MongoDB substitute and `aiosqlite` for an in-memory SQLite database, so **no live database connections are required** to run tests.

Test coverage includes API router mocks, external API client mocking, PostgreSQL/MongoDB integration helpers, and Celery task unit tests.

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | `development` / `staging` / `production` |
| `DEBUG` | `false` | Enables SQLAlchemy query echo |
| `ALLOWED_ORIGINS` | `["http://localhost:3000","http://localhost:5173","http://127.0.0.1:3000","http://127.0.0.1:5173"]` | CORS origins (JSON array) |
| `POSTGRES_USER` | `postgres` | DB username |
| `POSTGRES_PASSWORD` | — | DB password (**required**) |
| `POSTGRES_HOST` | `postgres-db` | Hostname (Docker service name) |
| `POSTGRES_DB` | `postgres` | Database name |
| `MONGO_URI` | — | Full MongoDB connection string (**required**) |
| `MONGO_DB` | `engagement_raw` | MongoDB database name |
| `REDIS_URL` | `redis://redis-broker:6379/0` | Cache / general Redis DB |
| `CELERY_BROKER_URL` | `redis://redis-broker:6379/1` | Celery task broker |
| `CELERY_RESULT_BACKEND` | `redis://redis-broker:6379/2` | Celery result store |
| `YOUTUBE_API_KEY` | — | Google Cloud YouTube Data API v3 key |
| `YOUTUBE_CACHE_TTL` | `3600` | YouTube API response cache TTL (seconds) |
| `YOUTUBE_DAILY_QUOTA_LIMIT` | `10000` | YouTube Data API v3 daily quota cap |
| `YOUTUBE_QUOTA_SAFETY_BUFFER` | `500` | Units reserved before proactive quota gating |
| `REDDIT_CLIENT_ID` | — | Reddit OAuth2 app client ID |
| `REDDIT_CLIENT_SECRET` | — | Reddit OAuth2 app secret |
| `REDDIT_USER_AGENT` | `EngageLens/3.0` | PRAW user-agent string |
| `REDDIT_RATE_LIMIT_CALLS_PER_MIN` | `60` | Reddit API token-bucket capacity (req/min) |
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` | Gemini model identifier |
| `SEMANTIC_SIMILARITY_THRESHOLD` | `0.55` | Cosine similarity cut-off for cross-platform content matching |
| `SEMANTIC_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | SentenceTransformer model for semantic linking |
| `VITE_API_TARGET` | `http://localhost:8000` | Frontend proxy target override (local dev only) |

---

## License

This project is licensed under the MIT License.
