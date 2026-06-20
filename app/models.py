from pydantic import BaseModel, Field
from typing import Literal

Provider = Literal["openai", "groq"]


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    provider: Provider = "openai"


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]


class ActionDetailsRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=50)


class ActionDetails(BaseModel):
    id: str
    title: str
    objective: str


class ActionDetailsResponse(BaseModel):
    actions: list[ActionDetails]


class ActionOrderRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=20)
    provider: Provider = "openai"


class ActionOrderResponse(BaseModel):
    answer: str
    sources: list[str]


class IndexResponse(BaseModel):
    indexed_rows: int
    message: str


class AppConfigResponse(BaseModel):
    default_chat_provider: Provider
    openai_model: str
    groq_model: str
