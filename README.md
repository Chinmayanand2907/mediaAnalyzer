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
- Dedicated Celery queues: `celery` (default), `youtube`, `reddit`.

### Sentiment Analysis
- Primary engine: **`cardiffnlp/twitter-roberta-base-sentiment-latest`** (HuggingFace Transformers) — a RoBERTa model fine-tuned on social media text.
- Automatic fallback to **NLTK VADER** when the transformer model cannot be loaded (e.g., cold-start without GPU).
- Produces **positive / neutral / negative** distribution scores persisted into PostgreSQL per account.

### Engagement Prediction
- **XGBoost regression model** trained on historical engagement features: view counts, like/comment ratios, publish hour/day-of-week, lag metrics, and sentiment scores.
- Multi-step **iterative forecasting** for the next N posts.
- Graceful fallback to a **moving-average baseline** when XGBoost is unavailable (e.g., missing `libomp` on macOS).
- In-process training helper for model creation or periodic re-training (`train_xgboost.py`).

### Cross-Platform Analytics
- **Shared video discovery** — scans Reddit comments for YouTube URLs, enriches matches with metadata, propagation delay, and audience sentiment from both platforms.
- **Sentiment comparison** — side-by-side positive/neutral/negative breakdown for the same content across YouTube and Reddit.
- **Topic correlation** — keyword and topic extraction from both platforms to surface overlapping discussion themes.
- **Normalized engagement index** (0–100) enabling like-for-like comparison between YouTube channels and Reddit communities.
- **Correlation summary** — single unified payload combining shared videos, engagement, sentiment, and topics.

### AI Analyst Chatbot
- Powered by **Google Gemini (gemini-2.5-flash-lite)** via the OpenAI-compatible API.
- Context is **dynamically injected at request time** — the backend fetches live metrics from MongoDB and PostgreSQL and embeds them into the system prompt before calling the LLM.
- Three specialist personas depending on active dashboard view:
  - `youtube` → **Video Performance Consultant**
  - `reddit` → **Community Management Specialist**
  - `cross-platform` → **Cross-Channel Strategist**
- Answers are grounded exclusively in real data; the model is explicitly prevented from hallucinating metrics.

### Interactive Dashboard (React + Vite)
- **YouTube View** — channel KPIs, per-video timeline, sentiment pie, keyword frequency bar chart, and comment table.
- **Reddit View** — subreddit stats (members, active users, posts/comments), sentiment distribution, trending keywords, and raw comment feed.
- **Cross-Platform View** — shared videos, sentiment comparison chart, topic correlation, and normalized engagement index.
- **ChatBot Panel** — floating chat window with context awareness based on the active view.
- Client-side in-memory analytics cache (`useAnalytics` hook) to avoid redundant API calls.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | React 18, Vite, Recharts, Lucide React, Vanilla CSS |
| **Backend API** | FastAPI 0.115, Uvicorn, Python 3.12 |
| **Task Queue** | Celery 5.5, Redis 7 |
| **ORM / Validation** | SQLModel, SQLAlchemy 2 (async), Pydantic v2 |
| **Databases** | PostgreSQL 17 (structured metrics), MongoDB Atlas (raw payloads & comments) |
| **ML / NLP** | HuggingFace Transformers (RoBERTa), NLTK VADER, XGBoost, Scikit-learn, Pandas, NumPy |
| **LLM / Chatbot** | Google Gemini (gemini-2.5-flash-lite), OpenAI-compatible SDK |
| **External APIs** | YouTube Data API v3 (`google-api-python-client`), Reddit API (`PRAW 8`) |
| **DevOps** | Docker, Docker Compose (5-service stack) |
| **Testing** | Pytest, pytest-asyncio |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    React + Vite                      │
│  YouTube View │ Reddit View │ Cross-Platform │ Chat  │
└────────────────────────┬────────────────────────────┘
                         │ HTTP (REST)
┌────────────────────────▼────────────────────────────┐
│                    FastAPI (Uvicorn)                  │
│  /api/v1/youtube  /reddit  /cross-platform  /chatbot │
└──────┬──────────────────────────────────┬───────────┘
       │ enqueue tasks                    │ query data
┌──────▼──────┐                  ┌────────▼──────────┐
│    Redis    │                  │   PostgreSQL 17    │
│  (broker +  │                  │  structured KPIs,  │
│   results)  │                  │  sentiment scores  │
└──────┬──────┘                  └────────────────────┘
       │ consume                          ▲
┌──────▼──────────────────┐              │ write processed
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

Requires local PostgreSQL, Redis, and MongoDB to be running (or use the helper scripts `start_dbs.sh` / `stop_dbs.sh`).

#### Backend

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# Terminal 1 — FastAPI
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — Celery worker
celery -A app.core.celery_app worker --loglevel=info --concurrency=4 -Q celery,youtube,reddit
```

> **macOS note:** XGBoost requires OpenMP. If you see a prediction fallback warning, run `brew install libomp` and restart the process.

#### Frontend

```bash
cd frontend
npm install
npm run dev
```

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
│   │   ├── config.py             # Pydantic Settings (env vars, DSNs)
│   │   └── celery_app.py         # Celery instance & queue definitions
│   ├── db/
│   │   ├── postgres.py           # SQLAlchemy async engine, ORM models
│   │   └── mongodb.py            # Motor async client, collection helpers
│   ├── models/                   # SQLModel table definitions
│   ├── schemas/                  # Pydantic request/response schemas
│   ├── services/
│   │   ├── analytics/
│   │   │   ├── sentiment_service.py   # RoBERTa + VADER sentiment engine
│   │   │   ├── prediction_engine.py   # XGBoost forecasting + MA fallback
│   │   │   └── train_xgboost.py       # Training helper script
│   │   └── external/
│   │       ├── youtube_client.py      # YouTube Data API v3 wrapper
│   │       └── reddit_client.py       # PRAW Reddit API wrapper
│   ├── tasks/
│   │   └── ingestion_tasks.py    # Celery tasks: ingest, sentiment, prediction
│   └── main.py                   # FastAPI app factory & lifespan hooks
│
├── frontend/                     # React + Vite dashboard
│   └── src/
│       ├── api/client.js         # Axios API wrappers
│       ├── components/
│       │   ├── charts/           # Recharts components (sentiment, engagement, topics)
│       │   ├── layout/           # Navbar, StatCard
│       │   ├── tables/           # CommentsTable
│       │   └── ChatBotPanel.jsx  # AI chatbot UI
│       ├── hooks/useAnalytics.js # In-memory caching hook
│       ├── pages/Dashboard.jsx   # Root page / layout shell
│       └── views/
│           ├── YoutubeView.jsx
│           ├── RedditView.jsx
│           └── CrossPlatformView.jsx
│
├── tests/                        # Pytest suite
│   ├── test_routers.py
│   ├── test_clients.py
│   ├── test_db.py
│   └── test_tasks.py
│
├── Dockerfile                    # Multi-stage build (builder → runtime)
├── docker-compose.yml            # 5-service orchestration
├── requirements.txt
├── .env.example                  # Environment variable template
└── pytest.ini
```

---

## Running Tests

```bash
# From the project root with .venv active
pytest -v
```

Test coverage includes API router mocks, external API client mocking, PostgreSQL/MongoDB integration helpers, and Celery task unit tests.

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | `development` / `staging` / `production` |
| `DEBUG` | `false` | Enables SQLAlchemy query echo |
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
| `REDDIT_CLIENT_ID` | — | Reddit OAuth2 app client ID |
| `REDDIT_CLIENT_SECRET` | — | Reddit OAuth2 app secret |
| `REDDIT_USER_AGENT` | `EngageLens/3.0` | PRAW user-agent string |
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` | Gemini model identifier (e.g. `gemini-2.5-flash-lite`) |

---

## License

This project is licensed under the MIT License.
