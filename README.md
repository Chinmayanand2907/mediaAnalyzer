# EngageIQ — Social Media Engagement Analyzer

<div align="center">
  <h3>Ingest · Analyze · Predict · Chat</h3>
  <p>A full-stack social media intelligence platform bridging YouTube and Reddit data with NLP sentiment analysis, XGBoost engagement forecasting, category-calibrated transfer learning, and a context-aware AI analyst chatbot.</p>
</div>

---

## Overview

**EngageIQ** is an end-to-end social media intelligence platform. It ingests raw data from YouTube and Reddit via their official APIs, stores it across a dual-database architecture (MongoDB for raw payloads and comments, PostgreSQL for structured metrics), runs Hugging Face RoBERTa sentiment analysis and XGBoost engagement forecasting in the background via Celery, and exposes everything through a FastAPI REST layer to a React 19 dashboard — complete with a live AI analyst chatbot powered by **DeepSeek V4.1 Flash via River.ai**.

---

## Features

### Data Ingestion
- **YouTube** — syncs channel metadata, individual video stats (views, likes, comments, publish timestamps), and audience comments via YouTube Data API v3.
- **Reddit** — extracts subreddit submissions, upvote ratios, comment trees, and community activity via PRAW.
- **Asynchronous Task Queue** — all heavy ingestion, sentiment inference, and model training run in the background via **Celery** workers with **Redis** as the message broker, keeping the FastAPI API fully non-blocking.
- **Dedicated Task Routing** — isolated queues (`celery`, `youtube`, `reddit`) ensure high-throughput processing and prevent API latency spikes.
- **Bulk Comment Writes** — YouTube comment ingestion uses MongoDB `bulk_write(ordered=False)` for maximum ingestion throughput.
- **Accurate Video Statistics** — video-level KPIs are aggregated directly per video payload to prevent comment-induced double counting.

### Sentiment Analysis
- **Primary Engine** — `cardiffnlp/twitter-roberta-base-sentiment-latest` (Hugging Face Transformers), fine-tuned on social media conversations.
- **VADER Fallback** — automated fallback to **NLTK VADER** if the transformer model is unavailable (e.g., cold start without GPU).
- **Non-blocking Inference** — async FastAPI route handlers offload sentiment inference to worker threads via `asyncio.to_thread`.
- **Persisted Metrics** — positive, neutral, and negative sentiment distributions are saved per channel and subreddit in PostgreSQL.

### Engagement Prediction & Category Benchmarks
- **XGBoost Regression Model** — predicts post-level engagement using historical signals: view counts, like/comment ratios, publish hour, day-of-week, lag metrics, and sentiment distribution.
- **Multi-Step Iterative Forecasting** — recursive multi-step forecasting for future posts.
- **Category Benchmarks & Transfer Learning** (`category_benchmarks.py`) — empirical priors across key content verticals (tech, gaming, entertainment, education, music, news). Handles cold-start and sparse-history channels (< 5 posts) with domain-calibrated baseline engagement, growth trends, and Bayesian shrinkage blending.
- **Moving Average Baseline Fallback** — graceful fallback when XGBoost or OpenMP (`libomp`) is absent on the host environment.
- **In-process Model Trainer** (`train_xgboost.py`) — utility script for initial training and periodic re-training.

### Deep Cross-Platform Analytics
- **Video Cross-Platform Search** (`/video-engagement`) — analyzes any YouTube video URL or 11-character Video ID across Reddit communities.
  - Video fingerprinting (channel title, extracted keywords, duration, description).
  - Multi-tier Reddit search combining URL matching, title/channel heuristics, and semantic verification.
  - Publish-window date filtering and image post exclusion.
- **Audience Response & Sentiment Gap Analysis** — side-by-side comparison between YouTube viewers and Reddit community sentiment, with automated disparity analysis.
- **Discussion Drill-Down** — lists matching Reddit submissions with upvote ratios, comment counts, author sentiments, top excerpts, and direct permalinks.
- **Shared Video Discovery** — identifies YouTube videos mentioned across Reddit threads with propagation delay metrics.
- **Topic Correlation** — extracts correlated themes, keywords, and discussion topics across both networks.
- **Normalized Engagement Index (0–100)** — standardizes metrics so YouTube channel performance can be directly compared with Reddit community engagement.

### Semantic Matching
- Powered by **Sentence-BERT** (`all-MiniLM-L6-v2`) with configurable cosine similarity threshold (`SEMANTIC_SIMILARITY_THRESHOLD`).
- **Persistent TF-IDF Fallback** — single persistent `TfidfVectorizer` shared across encode calls to ensure consistent embedding spaces even without transformer dependencies.

### AI Analyst Chatbot
- Powered by **DeepSeek V4.1 Flash via River.ai** (`deepseek-ai/DeepSeek-V4.1-Flash`) using the OpenAI-compatible SDK.
- **Dynamic Context Injection** — queries live metrics from MongoDB and PostgreSQL at request time, injecting real statistics directly into the system prompt.
- **In-Memory TTL Context Cache** — 60-second caching layer prevents redundant database queries during multi-turn chats.
- **Three Specialized Personas**:
  - `youtube` → **Video Performance Consultant**
  - `reddit` → **Community Management Specialist**
  - `cross-platform` → **Cross-Channel Strategist**
- **Strictly Grounded** — system prompts instruct the model to base insights solely on verified ingested data, eliminating hallucinations.

### Interactive Dashboard (React 19 + Vite + Tailwind CSS v4)
- **Modern UI Stack** — Built with React 19, Vite, Tailwind CSS v4 (`@tailwindcss/vite`), Lucide React icons, and Recharts.
- **YouTube View** — Channel KPIs, video timeline, sentiment breakdown pie chart, keyword frequency charts, and paginated comments table.
- **Reddit View** — Subreddit member counts, active user counters, sentiment distribution, trending keywords, and submission feed.
- **Cross-Platform View** — Tabbed interface (Deep Video Search & Subreddit Exploration), stat cards for YouTube Reach and Viral Latency, quick chips for recently analyzed videos (persisted in `localStorage`), and discussion tables.
- **Dockable ChatBot Panel** — Floating assistant with markdown formatting and active-view context awareness.
- **Client-Side Analytics Cache** — Custom `useAnalytics` hook avoids duplicate API calls during view toggling.
- **Vercel Ready** — Configured with `vercel.json` rewrites for seamless single-page application (SPA) routing.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | React 19, Vite 8, Tailwind CSS v4, Lucide React, Recharts |
| **Backend API** | FastAPI 0.115, Uvicorn, Python 3.12+ / 3.14 |
| **Task Queue & Broker** | Celery 5.5, Redis 7 |
| **Databases** | PostgreSQL 17 (structured KPIs), MongoDB Atlas (raw payloads & comments) |
| **ORM / Validation** | SQLModel, SQLAlchemy 2 (asyncpg / async_sessionmaker), Pydantic v2 |
| **Machine Learning & NLP** | Hugging Face Transformers (RoBERTa), NLTK VADER, XGBoost, Scikit-learn, Sentence-BERT (`all-MiniLM-L6-v2`) |
| **LLM / AI Chatbot** | DeepSeek V4.1 Flash via River.ai (`deepseek-ai/DeepSeek-V4.1-Flash`), AsyncOpenAI SDK |
| **External APIs** | YouTube Data API v3, Reddit API (PRAW 8) |
| **Container & Cloud** | Docker, Docker Compose, Single-Container Entrypoint (`start.sh` for Hugging Face Spaces / Render) |
| **Testing** | Pytest, pytest-asyncio, pytest-mock, mongomock-motor, aiosqlite |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    React 19 + Vite Dashboard                    │
│   YouTube View  │  Reddit View  │  Cross-Platform  │  AI Chat   │
└────────────────────────────────┬────────────────────────────────┘
                                 │ HTTP (REST) / Vite Proxy
┌────────────────────────────────▼────────────────────────────────┐
│                        FastAPI (Uvicorn)                        │
│   /api/v1/youtube   /reddit   /cross-platform   /chatbot        │
└──────┬──────────────────────────────────────────────────┬───────┘
       │ enqueue ingestion / analytics                    │ query structured metrics
┌──────▼──────┐                                  ┌────────▼──────────┐
│    Redis    │                                  │   PostgreSQL 17   │
│  (broker +  │                                  │  accounts, KPIs,  │
│  rate-limit │                                  │  sentiment scores │
│   + cache)  │                                  └───────────────────┘
└──────┬──────┘                                           ▲
       │ consume routed tasks                             │ write metrics
┌──────▼──────────────────────────┐                       │
│         Celery Workers          │───────────────────────┘
│  - Queues: youtube, reddit      │
│  - RoBERTa / VADER Sentiment    │──────────► MongoDB Atlas
│  - XGBoost / Category Priors    │             (raw video payloads,
└──────────────┬──────────────────┘              comments, threads)
               │ fetch raw data
       ┌───────┴────────┐
       │ YouTube API v3 │  Reddit API (PRAW)
       └────────────────┘
```

---

## Getting Started

### Prerequisites

- **Python 3.12+** (or virtualenv with dependencies installed)
- **Node.js 18+** & **npm**
- **Docker & Docker Compose** (optional, for containerized run)
- **MongoDB Atlas** cluster URI (or local MongoDB)
- **PostgreSQL 17** & **Redis 7** (via Docker, DBngin, or Homebrew)

---

### 1. Configuration (`.env`)

Clone the repository and copy the environment template:

```bash
git clone https://github.com/Chinmayanand2907/mediaAnalyzer.git
cd mediaAnalyzer

cp .env.example .env
```

Open `.env` and fill in your keys:

| Variable | Description / Source |
|---|---|
| `DATABASE_URL` or `POSTGRES_*` | PostgreSQL connection string (local or cloud Neon/Supabase) |
| `MONGO_URI` | MongoDB Atlas connection string (`mongodb+srv://...`) |
| `REDIS_URL` | Redis URL (default: `redis://localhost:6379/0` or `redis://127.0.0.1:6379/0`) |
| `YOUTUBE_API_KEY` | Google Cloud Console → YouTube Data API v3 |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | Reddit App Preferences → Script Application |
| `RIVER_API_KEY` | [River.ai](https://river.ai) → Dashboard → API Keys (for DeepSeek AI Chatbot) |

---

### 2. Running Locally

You can run EngageIQ using **Native Development** or **Docker Compose**.

#### Method A: Native Local Development (Recommended for Development)

1. **Start Databases (PostgreSQL & Redis):**
   ```bash
   ./start_dbs.sh
   ```
   *(Uses macOS DBngin paths by default. You can also start Postgres and Redis via Homebrew or the DBngin GUI).*

2. **Start FastAPI Backend (Terminal 1):**
   ```bash
   source .venv/bin/activate
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

3. **Start Celery Worker (Terminal 2):**
   ```bash
   source .venv/bin/activate
   celery -A app.core.celery_app worker --loglevel=info -Q celery,youtube,reddit
   ```

   > **macOS Note:** XGBoost requires OpenMP. If you see a prediction fallback warning, run `brew install libomp`.

4. **Start Vite React Dashboard (Terminal 3):**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

5. **Stop Databases when finished:**
   ```bash
   ./stop_dbs.sh
   ```

---

#### Method B: Docker Compose (All-in-One Container)

Runs all five services (PostgreSQL, Redis, FastAPI, Celery, and React frontend) containerized:

```bash
docker compose up -d --build
```

To stop containers:
```bash
docker compose down
```

---

#### Method C: Unified Container / Cloud Deployment (`start.sh`)

[`start.sh`](file:///Users/chinmay/Desktop/Major Project/start.sh) is configured for unified container hosts like **Hugging Face Spaces** or **Render**:
- Starts embedded Redis daemon
- Starts Celery worker in detached background mode
- Launches Uvicorn in the foreground on `$PORT` (default `7860`)

```bash
chmod +x start.sh
./start.sh
```

---

### Service Endpoints

| Service | URL |
|---|---|
| 🖥️ **Frontend Dashboard** | [http://localhost:5173](http://localhost:5173) |
| ⚙️ **Backend REST API** | [http://localhost:8000](http://localhost:8000) |
| 📖 **Interactive Swagger Docs** | [http://localhost:8000/docs](http://localhost:8000/docs) |
| 🗄️ **PostgreSQL** | `localhost:5432` |
| 🔄 **Redis Broker** | `localhost:6379` |

---

## Project Structure

```
mediaAnalyzer/
│
├── app/                                # FastAPI backend
│   ├── api/v1/
│   │   ├── schemas.py                  # Pydantic request / response schemas
│   │   └── routers/
│   │       ├── youtube.py              # /api/v1/youtube — sync, metrics, sentiment
│   │       ├── reddit.py               # /api/v1/reddit  — sync, sentiment, keywords
│   │       ├── cross_platform.py       # /api/v1/cross-platform — video engagement, correlation
│   │       └── chatbot.py              # /api/v1/chatbot — DeepSeek via River.ai with live context
│   ├── core/
│   │   ├── config.py                   # Pydantic Settings (env vars, DSNs, quota limits)
│   │   ├── celery_app.py               # Celery instance, queues & task routing
│   │   ├── cache.py                    # Redis async cache (loop-safe singleton)
│   │   └── rate_limiter.py             # Token-bucket rate limiter (Redis Lua + in-memory fallback)
│   ├── db/
│   │   ├── postgres.py                 # SQLAlchemy async engine, async_sessionmaker, models
│   │   └── mongodb.py                  # Motor async client, collection helpers, indexes
│   ├── models/                         # SQLModel table definitions
│   ├── services/
│   │   ├── analytics/
│   │   │   ├── sentiment_service.py    # RoBERTa + VADER sentiment engine (thread-safe)
│   │   │   ├── prediction_engine.py    # XGBoost forecasting + MA fallback
│   │   │   ├── category_benchmarks.py  # Category priors, transfer learning & Bayesian shrinkage
│   │   │   ├── semantic_matcher.py     # Sentence-BERT / TF-IDF cross-platform matcher
│   │   │   └── train_xgboost.py        # Model training helper script
│   │   └── external/
│   │       ├── youtube_client.py       # YouTube Data API v3 wrapper
│   │       └── reddit_client.py        # PRAW Reddit API wrapper
│   ├── tasks/
│   │   └── ingestion_tasks.py          # Celery background tasks (bulk writes, sentiment, predictions)
│   └── main.py                         # FastAPI app factory & lifespan hooks
│
├── frontend/                           # React 19 + Vite dashboard
│   ├── vercel.json                     # Vercel SPA routing configuration
│   ├── vite.config.js                  # Vite configuration & backend proxy
│   └── src/
│       ├── api/client.js               # Axios API client functions
│       ├── components/
│       │   ├── charts/                 # Recharts components (sentiment, engagement, topics)
│       │   ├── layout/                 # Navbar, StatCard
│       │   ├── tables/                 # CommentsTable, SharedVideosTable
│       │   └── ChatBotPanel.jsx        # DeepSeek AI Chatbot floating panel
│       ├── hooks/useAnalytics.js       # In-memory analytics caching hook
│       ├── pages/Dashboard.jsx         # Root dashboard shell
│       └── views/
│           ├── YoutubeView.jsx         # YouTube channel analytics view
│           ├── RedditView.jsx          # Reddit community analytics view
│           └── CrossPlatformView.jsx   # Deep video search, sentiment disparity & drill-down
│
├── tests/                              # Pytest test suite
│   ├── conftest.py                     # Shared fixtures (mongomock-motor, aiosqlite)
│   ├── test_api_clients.py             # External API mock tests
│   ├── test_clients.py                 # Client initialization tests
│   ├── test_db.py                      # Database helper tests
│   ├── test_prediction_engine.py       # XGBoost and category benchmark tests
│   ├── test_reddit_rate_limiter.py     # Token-bucket rate limiter tests
│   ├── test_routers.py                 # API router integration tests
│   ├── test_semantic_matcher.py        # Sentence-BERT & TF-IDF similarity tests
│   ├── test_tasks.py                   # Celery task execution tests
│   └── test_youtube_quota_and_cache.py # YouTube quota safety buffer tests
│
├── Dockerfile                          # Multi-stage production build
├── docker-compose.yml                  # 5-service local orchestration
├── start.sh                            # Cloud / containerized entrypoint
├── start_dbs.sh                        # Local macOS DB startup helper
├── stop_dbs.sh                         # Local macOS DB teardown helper
├── requirements.txt                    # Python dependencies
├── .env.example                        # Environment variable template
└── pytest.ini                          # Pytest configuration
```

---

## Running Tests

```bash
# Activate virtual environment
source .venv/bin/activate

# Run full test suite
pytest -v
```

The test suite uses `mongomock-motor` for in-memory MongoDB simulation and `aiosqlite` for in-memory SQLite tables, meaning **no live external database connection is required to run the tests**.

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | Environment mode (`development` / `staging` / `production`) |
| `DEBUG` | `false` | Enables SQL query echo (keep `false` in production) |
| `ALLOWED_ORIGINS` | `["http://localhost:3000","http://localhost:5173"]` | CORS allowed origins (JSON array) |
| `DATABASE_URL` | — | Full PostgreSQL connection string (takes precedence if provided) |
| `POSTGRES_USER` | `postgres` | PostgreSQL username |
| `POSTGRES_PASSWORD` | — | PostgreSQL password (**required** if `DATABASE_URL` not set) |
| `POSTGRES_HOST` | `postgres-db` (Docker) / `localhost` | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_DB` | `postgres` | PostgreSQL database name |
| `MONGO_URI` | — | MongoDB Atlas connection string (**required**) |
| `MONGO_DB` | `engagement_raw` | MongoDB database name |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis caching and rate-limiting connection URI |
| `CELERY_BROKER_URL` | `redis://127.0.0.1:6379/1` | Celery broker URL |
| `CELERY_RESULT_BACKEND` | `redis://127.0.0.1:6379/2` | Celery result backend URL |
| `YOUTUBE_API_KEY` | — | Google Cloud YouTube Data API v3 key |
| `YOUTUBE_CACHE_TTL` | `3600` | YouTube API response cache TTL in seconds |
| `YOUTUBE_DAILY_QUOTA_LIMIT` | `10000` | Daily quota cap for YouTube API |
| `YOUTUBE_QUOTA_SAFETY_BUFFER` | `500` | Buffer reserved before proactive quota gating |
| `REDDIT_CLIENT_ID` | — | Reddit script app client ID |
| `REDDIT_CLIENT_SECRET` | — | Reddit script app secret |
| `REDDIT_USER_AGENT` | `EngageLens/3.0` | User agent for Reddit API requests |
| `REDDIT_RATE_LIMIT_CALLS_PER_MIN` | `60` | Token-bucket capacity for Reddit requests |
| `RIVER_API_KEY` | — | River.ai API key for DeepSeek LLM queries |
| `RIVER_MODEL` | `deepseek-ai/DeepSeek-V4.1-Flash` | LLM model identifier |
| `SEMANTIC_SIMILARITY_THRESHOLD` | `0.55` | Cosine similarity threshold for content matching |
| `SEMANTIC_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | SentenceTransformer model name |
| `VITE_API_TARGET` | `http://localhost:8000` | Vite dev proxy target override |
| `VITE_API_BASE` | — | API base URL for deployed frontend (e.g. on Vercel) |

---

## License

This project is licensed under the MIT License.
