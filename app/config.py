from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_model: str
    openai_embedding_model: str
    groq_api_key: str
    groq_model: str
    default_chat_provider: str
    database_url: str
    target_table: str
    target_id_column: str
    target_text_columns: list[str]
    max_rows: int
    top_k: int
    max_context_docs: int
    max_context_chars: int
    max_doc_chars: int


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def get_settings() -> Settings:
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        openai_embedding_model=os.getenv(
            "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
        ),
        groq_api_key=os.getenv("GROQ_API_KEY", os.getenv("GROQKEY", "")),
        groq_model=os.getenv("GROQ_MODEL", "qwen/qwen3-32b"),
        default_chat_provider=os.getenv("DEFAULT_CHAT_PROVIDER", "openai"),
        database_url=os.getenv("DATABASE_URL", ""),
        target_table=os.getenv("TARGET_TABLE", ""),
        target_id_column=os.getenv("TARGET_ID_COLUMN", "id"),
        target_text_columns=_split_csv(os.getenv("TARGET_TEXT_COLUMNS", "")),
        max_rows=int(os.getenv("MAX_ROWS", "2000")),
        top_k=int(os.getenv("TOP_K", "6")),
        max_context_docs=int(os.getenv("MAX_CONTEXT_DOCS", "3")),
        max_context_chars=int(os.getenv("MAX_CONTEXT_CHARS", "12000")),
        max_doc_chars=int(os.getenv("MAX_DOC_CHARS", "2500")),
    )
