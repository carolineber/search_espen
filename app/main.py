from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.models import (
    ActionDetailsRequest,
    ActionDetailsResponse,
    ActionOrderRequest,
    ActionOrderResponse,
    AppConfigResponse,
    ChatRequest,
    ChatResponse,
    IndexResponse,
)
from app.rag import answer_question, build_index, get_action_details, suggest_action_order

app = FastAPI(title="Chatbot RAG com OpenAI + Groq + Banco")
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path("frontend")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def home() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/api/config", response_model=AppConfigResponse)
def app_config() -> AppConfigResponse:
    return AppConfigResponse(
        default_chat_provider=settings.default_chat_provider,
        openai_model=settings.openai_model,
        groq_model=settings.groq_model,
    )


@app.post("/api/index", response_model=IndexResponse)
def index_database() -> IndexResponse:
    try:
        indexed = build_index(settings)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return IndexResponse(
        indexed_rows=indexed,
        message="Indexacao concluida com sucesso.",
    )


@app.post("/api/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    try:
        answer, sources = answer_question(body.question, settings, body.provider)
    except FileNotFoundError as exc:
        try:
            build_index(settings)
            answer, sources = answer_question(body.question, settings, body.provider)
        except Exception as index_exc:
            raise HTTPException(status_code=400, detail=str(index_exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ChatResponse(answer=answer, sources=sources)


@app.post("/api/actions/details", response_model=ActionDetailsResponse)
def action_details(body: ActionDetailsRequest) -> ActionDetailsResponse:
    try:
        actions = get_action_details(settings, body.ids)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ActionDetailsResponse(actions=actions)


@app.post("/api/actions/order", response_model=ActionOrderResponse)
def action_order(body: ActionOrderRequest) -> ActionOrderResponse:
    try:
        answer, sources = suggest_action_order(settings, body.ids, body.provider)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ActionOrderResponse(answer=answer, sources=sources)
