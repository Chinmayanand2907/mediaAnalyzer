# EngageIQ: Full-Stack Social Media Analytics Platform

<div align="center">
  <h3>Aggregate, Analyze, and Visualize Data from Social Media in Real-Time</h3>
</div>

---

**EngageIQ** is a comprehensive full-stack social media analytics platform that allows you to seamlessly ingest data from YouTube and Reddit, analyze its sentiment using state-of-the-art NLP models, and visualize engagement metrics on an interactive, real-time dashboard. The platform also features an integrated AI Analyst Chatbot to provide context-aware insights into your analytics.

## 🚀 Key Features

- **Multi-Platform Data Ingestion**: Fetch posts, videos, and comments simultaneously from YouTube and Reddit APIs.
- **Deep Sentiment Analysis**: Evaluates textual data sentiment using the HuggingFace RoBERTa model to accurately classify positive, negative, and neutral engagements.
- **Contextual AI Analyst Chatbot**: Powered by **Groq Cloud LLM (xAI/Llama models)**, allowing you to ask natural language queries about your social media metrics and trends.
- **Asynchronous Task Processing**: Uses **Celery & Redis** to handle high-volume background data ingestion without blocking the main application.
- **Dual-Database Architecture**: 
  - **MongoDB Atlas** for scalable, schema-less raw JSON storage.
  - **PostgreSQL** for normalized, structured transactional data (users, processed videos/posts, computed metrics).
- **Interactive React Dashboard**: A polished **React + Vite** frontend providing rich data visualizations, cross-platform comparative views, and a dedicated AI chat panel.
- **Containerized Environment**: The entire stack is orchestrated with **Docker Compose**, running across 5 interconnected services for effortless deployment.

## 🛠️ Tech Stack

### Frontend
- **React.js & Vite**: Fast, modern frontend framework.
- **JavaScript (JSX)**: Core logic and component structure.
- **Tailwind / Custom CSS**: For a responsive, beautiful UI.

### Backend & Core Services
- **FastAPI (Python)**: High-performance async API backend.
- **Celery**: Distributed task queue for asynchronous data processing.
- **Redis**: In-memory message broker and caching layer.
- **SQLAlchemy & Pydantic**: ORM and data validation.

### Databases
- **PostgreSQL**: Relational database for structured metrics.
- **MongoDB**: NoSQL document database for raw data dumps.

### AI & Machine Learning
- **HuggingFace (RoBERTa)**: Sentiment analysis engine.
- **Groq Cloud LLM**: High-speed LLM for the AI Analyst chatbot.

### DevOps
- **Docker & Docker Compose**: Containerization and orchestration.

## 🏗️ System Architecture

1. **Ingestion Layer**: Scheduled Celery tasks query Reddit (PRAW) and YouTube (Data API v3) endpoints. 
2. **Raw Storage**: Unprocessed data is instantly dumped into MongoDB.
3. **Processing & NLP Layer**: Background workers extract text, pass it through the RoBERTa sentiment model, and calculate engagement scores.
4. **Structured Storage**: The refined, structured insights are committed to PostgreSQL.
5. **API Layer**: The FastAPI server acts as a bridge, exposing REST endpoints to serve data to the frontend and manage AI chatbot interactions.
6. **Presentation Layer**: The React dashboard fetches the endpoints to render charts, graphs, and the Chatbot UI.

## 🚦 Getting Started

### Prerequisites

Ensure you have the following installed on your machine:
- [Docker](https://docs.docker.com/get-docker/) & Docker Compose
- [Node.js](https://nodejs.org/) (for optional local frontend dev)
- [Python 3.9+](https://www.python.org/) (for optional local backend dev)

### 1. Environment Setup

Clone the repository:
```bash
git clone https://github.com/Chinmayanand2907/mediaAnalyzer.git
cd mediaAnalyzer
```

Copy the example environment file to create your own `.env`:
```bash
cp .env.example .env
```

Open the `.env` file and populate it with your specific API credentials:
- **Database URIs**: PostgreSQL and MongoDB.
- **YouTube Data API v3 Key**
- **Reddit API (PRAW)**: Client ID and Client Secret
- **Groq Cloud API Key**: For the Chatbot functionality

### 2. Running the Application via Docker (Recommended)

Start the entire application stack using Docker Compose:

```bash
docker-compose up -d --build
```

Once the containers are up and running, you can access the services at:
- 🖥️ **Frontend Dashboard**: [http://localhost:5173](http://localhost:5173)
- ⚙️ **Backend API**: [http://localhost:8000](http://localhost:8000)
- 📖 **Swagger API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

### 3. Local Development (Without Docker)

#### Backend Setup

```bash
# From the root directory
python -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`

pip install -r requirements.txt
uvicorn app.main:app --reload
```

*Note: Running the backend locally requires a local or remote instance of PostgreSQL, MongoDB, and Redis to be running.*

#### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

## 📂 Project Structure

```
mediaAnalyzer/
│
├── app/                  # FastAPI Backend Source Code
│   ├── api/              # Route handlers and API endpoints
│   ├── core/             # Configuration and database setups
│   ├── db/               # PostgreSQL & MongoDB connections
│   ├── models/           # Database schemas
│   ├── services/         # Business logic, NLP models, External API clients
│   └── tasks/            # Celery async tasks
│
├── frontend/             # React + Vite Frontend
│   ├── src/
│   │   ├── components/   # Reusable UI elements & charts
│   │   ├── views/        # Main pages (Dashboard, YouTube, Reddit)
│   │   └── api/          # Axios/fetch API client wrappers
│   └── package.json
│
├── tests/                # Pytest integration & unit tests
├── docker-compose.yml    # Docker orchestration configuration
├── .env.example          # Template for environment variables
└── README.md             # Project documentation
```

## 📄 License

This project is licensed under the MIT License.
