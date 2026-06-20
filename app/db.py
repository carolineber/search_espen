from __future__ import annotations

from sqlalchemy import create_engine, text

from app.config import Settings


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def fetch_rows(settings: Settings) -> list[dict]:
    if not settings.database_url:
        raise ValueError("DATABASE_URL nao configurada.")
    if not settings.target_table:
        raise ValueError("TARGET_TABLE nao configurada.")
    if not settings.target_text_columns:
        raise ValueError("TARGET_TEXT_COLUMNS nao configurada.")

    columns = [settings.target_id_column] + settings.target_text_columns
    quoted_columns = ", ".join([_quote_identifier(col) for col in columns])

    query = text(
        f"SELECT {quoted_columns} FROM {_quote_identifier(settings.target_table)} LIMIT :max_rows"
    )

    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        result = connection.execute(query, {"max_rows": settings.max_rows})
        return [dict(row._mapping) for row in result]


def fetch_table_rows(settings: Settings, columns: list[str] | None = None) -> list[dict]:
    if not settings.database_url:
        raise ValueError("DATABASE_URL nao configurada.")
    if not settings.target_table:
        raise ValueError("TARGET_TABLE nao configurada.")

    selected_columns = "*"
    if columns:
        selected_columns = ", ".join([_quote_identifier(col) for col in columns])

    query = text(
        f"SELECT {selected_columns} FROM {_quote_identifier(settings.target_table)} LIMIT :max_rows"
    )

    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        result = connection.execute(query, {"max_rows": settings.max_rows})
        return [dict(row._mapping) for row in result]
