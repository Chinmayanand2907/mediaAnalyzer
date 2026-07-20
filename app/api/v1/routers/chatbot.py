"""
Chatbot Router  —  /api/v1/chatbot
====================================

Endpoints
---------
POST /query   — Accept a user question + active dashboard context, inject a
                dynamic system prompt, and return an AI answer from Groq Cloud
                (LLaMA 3.3 70B). Fast inference, free tier available.

Context → System Prompt mapping
--------------------------------
  youtube       →  Video Performance Consultant
  reddit        →  Community Management Specialist
  cross-platform→  Cross-Channel Strategist (synthesises both)
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from openai import AsyncOpenAI, APIConnectionError, AuthenticationError
from pydantic import BaseModel, Field

from app.core.config import get_settings

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

# ─── System Prompt Templates ──────────────────────────────────────────────────

_SYSTEM_PROMPTS: dict[str, str] = {
    "youtube": (
        "You are an expert YouTube Video Performance Consultant with deep knowledge "
        "of the YouTube algorithm, audience retention, CTR optimisation, and "
        "sentiment-driven content strategy. "
        "The user is viewing a live analytics dashboard that tracks their YouTube "
        "channels — including subscriber counts, view counts, likes, and comment "
        "sentiment distributions (positive/neutral/negative). "
        "Give concise, data-informed, actionable advice. "
        "If the user asks about their numbers, encourage them to mention the specific "
        "metrics they see on screen. "
        "Keep answers under 250 words unless a detailed breakdown is explicitly asked for."
    ),
    "reddit": (
        "You are an expert Reddit Community Management Specialist with deep "
        "knowledge of subreddit growth strategies, upvote mechanics, community "
        "engagement tactics, keyword trend analysis, and sentiment management. "
        "The user is viewing a live analytics dashboard that tracks their Reddit "
        "subreddits — including member counts, trending keywords, post volume, "
        "and comment sentiment. "
        "Give concise, community-first, actionable advice. "
        "Keep answers under 250 words unless a detailed breakdown is explicitly asked for."
    ),
    "cross-platform": (
        "You are an expert Cross-Platform Content Strategist specialising in "
        "bridging YouTube and Reddit audiences. You synthesise insights from both "
        "platforms to create integrated channel playbooks. "
        "The user is viewing a live cross-platform analytics dashboard that maps "
        "YouTube video performance against Reddit discussion volume and upvote "
        "velocity — enabling content propagation analysis. "
        "Give concise, integrated, actionable advice that leverages data from both "
        "platforms simultaneously. "
        "Keep answers under 300 words unless a detailed breakdown is explicitly asked for."
    ),
}

# ─── Schemas ─────────────────────────────────────────────────────────────────

PlatformContext = Literal["youtube", "reddit", "cross-platform"]


class ChatbotRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="The user's natural-language question",
        examples=["Why is my comment sentiment trending negative?"],
    )
    context: PlatformContext = Field(
        ...,
        description="Active dashboard platform: 'youtube' | 'reddit' | 'cross-platform'",
        examples=["youtube"],
    )


class ChatbotResponse(BaseModel):
    answer: str = Field(..., description="AI-generated response text")
    context: str = Field(..., description="Platform context that was used")
    model: str = Field(..., description="LLM model that produced the response")


# ─── Endpoint ────────────────────────────────────────────────────────────────

@router.post(
    "/query",
    response_model=ChatbotResponse,
    summary="Query the context-aware AI analyst",
    description=(
        "Submit a question along with the active dashboard platform context. "
        "The system prompt dynamically adapts to act as the most relevant "
        "expert persona for the given context."
    ),
)
async def chatbot_query(payload: ChatbotRequest) -> ChatbotResponse:
    """
    Dynamically select a system prompt based on `context`, call the Grok API
    (OpenAI-compatible), and return the AI response.
    """
    settings = get_settings()

    if not settings.GROQ_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Chatbot is not configured. Please set GROQ_API_KEY in your "
                ".env file. Get a free API key at https://console.groq.com"
            ),
        )

    system_prompt = _SYSTEM_PROMPTS[payload.context]

    # Groq Cloud uses an OpenAI-compatible API — just swap the base_url
    client = AsyncOpenAI(
        api_key=settings.GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1",
    )

    model = "llama-3.3-70b-versatile"

    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": payload.question},
            ],
            temperature=0.7,
            max_tokens=512,
        )
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid GROQ_API_KEY. Please verify your key at https://console.groq.com",
        )
    except APIConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not connect to the Grok API: {exc}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error from LLM: {exc}",
        )

    answer = completion.choices[0].message.content or "No response generated."

    return ChatbotResponse(
        answer=answer,
        context=payload.context,
        model=model,
    )
