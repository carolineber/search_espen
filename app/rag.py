from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from pathlib import Path

from openai import OpenAI
from groq import Groq

from app.config import Settings
from app.db import fetch_rows, fetch_table_rows

# In Vercel serverless, code directory is read-only; use /tmp for runtime artifacts.
INDEX_PATH = (
    Path("/tmp/vector_index.json")
    if os.getenv("VERCEL") == "1"
    else Path("data/vector_index.json")
)


def _row_to_text(row: dict, text_columns: list[str]) -> str:
    parts: list[str] = []
    for col in text_columns:
        value = row.get(col)
        if value is None:
            continue
        text_value = str(value).strip()
        if text_value:
            parts.append(f"{col}: {text_value}")
    return "\n".join(parts)


def _embed_texts(client: OpenAI, model: str, texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


def _tokenize(text: str) -> set[str]:
    tokens: list[str] = []
    current: list[str] = []

    for char in text.lower():
        if char.isalnum():
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []

    if current:
        tokens.append("".join(current))

    return {token for token in tokens if len(token) > 2}


STOPWORDS = {
    "sobre",
    "para",
    "preciso",
    "fazer",
    "curso",
    "cursos",
    "acao",
    "acoes",
    "trilha",
    "trilhas",
    "quero",
    "gostaria",
    "necessito",
    "uma",
    "uns",
    "das",
    "dos",
    "com",
    "por",
    "que",
    "qual",
    "quais",
    "voce",
    "pode",
    "indicar",
    "sugerir",
    "recomendar",
    "recomenda",
    "sugere",
    "sugira",
    "indique",
}


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(value.lower().strip().split())


def _meaningful_tokens(text: str) -> set[str]:
    return {token for token in _tokenize(_normalize_text(text)) if token not in STOPWORDS}


def _find_row_column(row: dict, wanted_column: str) -> str | None:
    wanted = _normalize_text(wanted_column)
    for column in row:
        if _normalize_text(str(column)) == wanted:
            return str(column)
    return None


def _row_value(row: dict, preferred_column: str, fallback_label: str | None = None) -> str:
    column = _find_row_column(row, preferred_column)
    if column:
        value = str(row.get(column) or "").strip()
        if value:
            return value

    if fallback_label:
        return _extract_content_value(str(row.get("conteudo") or ""), fallback_label)

    return ""


def _extract_content_value(content: str, label: str) -> str:
    label_pattern = re.escape(label)
    match = re.search(rf"(?m)^{label_pattern}:\s*(.+)$", content)
    return match.group(1).strip() if match else ""


def _looks_like_recommendation_question(question: str) -> bool:
    normalized = _normalize_text(question)
    recommendation_terms = [
        "preciso",
        "quero",
        "gostaria",
        "necessito",
        "recomenda",
        "recomendar",
        "sugere",
        "sugerir",
        "sugira",
        "indica",
        "indicar",
        "indique",
        "qual curso",
        "quais cursos",
        "qual acao",
        "quais acoes",
        "qual trilha",
        "quais trilhas",
    ]
    learning_terms = ["curso", "cursos", "trilha", "trilhas", "acao", "acoes", "capacitacao"]
    return any(term in normalized for term in recommendation_terms) and any(
        term in normalized for term in learning_terms
    )


def _score_weighted_field(question_tokens: set[str], value: str, weight: float) -> tuple[float, set[str]]:
    value_tokens = _meaningful_tokens(value)
    matched_tokens = question_tokens & value_tokens
    if not matched_tokens:
        return 0.0, set()

    coverage = len(matched_tokens) / max(1, len(question_tokens))
    density = len(matched_tokens) / max(1, len(value_tokens))
    score = weight * ((coverage * 0.75) + (density * 0.25))
    return score, matched_tokens


def _format_recommendation_reason(matched_fields: list[str]) -> str:
    if not matched_fields:
        return "aderência textual aos campos priorizados"
    return "aderência em " + ", ".join(matched_fields[:4])


def _split_associated_module_ids(modules: str) -> list[str]:
    seen: set[str] = set()
    module_ids: list[str] = []
    for module_id in re.split(r"[;,]", modules):
        clean_id = module_id.strip()
        if clean_id and clean_id not in seen:
            seen.add(clean_id)
            module_ids.append(clean_id)
    return module_ids


def _build_ae_title_lookup(rows: list[dict]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for row in rows:
        ae_id = _row_value(row, "ID AE", "ID AE")
        title = _row_value(row, "3. Nome da Ação", "3. Nome da Ação") or str(
            row.get("titulo") or ""
        )
        if ae_id and title:
            lookup[ae_id] = title
    return lookup


def _format_associated_modules(modules: str, ae_title_lookup: dict[str, str]) -> list[str]:
    module_lines: list[str] = []
    for module_id in _split_associated_module_ids(modules):
        title = ae_title_lookup.get(module_id, "Nome da ação não encontrado")
        module_lines.append(f"  - {module_id}: {title}")
    return module_lines


def _rows_by_ae_id(settings: Settings, ids: list[str]) -> list[dict]:
    wanted_ids = []
    seen_ids: set[str] = set()
    for item in ids:
        ae_id = item.strip()
        if ae_id and ae_id not in seen_ids:
            seen_ids.add(ae_id)
            wanted_ids.append(ae_id)

    if not wanted_ids:
        return []

    rows = fetch_table_rows(settings)
    row_lookup = {_row_value(row, "ID AE", "ID AE"): row for row in rows}
    return [row_lookup[ae_id] for ae_id in wanted_ids if ae_id in row_lookup]


def get_action_details(settings: Settings, ids: list[str]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for row in _rows_by_ae_id(settings, ids):
        objective = _row_value(row, "11. Objetivos Específicos", "11. Objetivos Específicos")
        if not objective:
            objective = _row_value(
                row,
                "Objetivo de Aprendizagem MCN",
                "Objetivo de Aprendizagem MCN",
            )

        actions.append(
            {
                "id": _row_value(row, "ID AE", "ID AE"),
                "title": _row_value(row, "3. Nome da Ação", "3. Nome da Ação")
                or str(row.get("titulo") or ""),
                "objective": objective or "Objetivo não informado no cadastro.",
            }
        )
    return actions


def suggest_action_order(
    settings: Settings, ids: list[str], provider: str = "openai"
) -> tuple[str, list[str]]:
    rows = _rows_by_ae_id(settings, ids)
    if not rows:
        return ("Nao encontrei as ações selecionadas no banco.", [])

    action_blocks: list[str] = []
    sources: list[str] = []
    for row in rows:
        ae_id = _row_value(row, "ID AE", "ID AE")
        title = _row_value(row, "3. Nome da Ação", "3. Nome da Ação") or str(
            row.get("titulo") or ""
        )
        objective = _row_value(row, "11. Objetivos Específicos", "11. Objetivos Específicos")
        competence = _row_value(row, "10. Competência", "10. Competência") or _row_value(
            row, "Competência MCN", "Competência MCN"
        )
        axis = _row_value(row, "6. Eixo", "6. Eixo") or _row_value(
            row, "Eixo Funcional MCN", "Eixo Funcional MCN"
        )
        action_type = _row_value(row, "4. Tipo da Ação", "4. Tipo da Ação")

        action_blocks.append(
            "\n".join(
                [
                    f"ID AE: {ae_id}",
                    f"Nome da Ação: {title}",
                    f"Objetivos Específicos: {objective}",
                    f"Competência: {competence}",
                    f"Eixo: {axis}",
                    f"Tipo da Ação: {action_type}",
                ]
            )
        )
        sources.append(f"{settings.target_table}:{row.get('id', ae_id or 'sem_id')}")

    system_prompt = (
        "Você é especialista em desenho instrucional para escolas de governo. "
        "Use apenas as ações fornecidas para sugerir uma ordem de aplicação."
    )
    user_prompt = (
        "A pessoa selecionou estas ações educativas da Base ESPEN:\n\n"
        + "\n\n---\n\n".join(action_blocks)
        + "\n\nResponda em Markdown, em português, com o título "
        "'Sugestão de trilha'. Traga uma lista numerada das ações ordenadas "
        "com ID AE e Nome da Ação. Para cada item, explique em uma frase por que "
        "essa ação deve vir nessa posição. Não invente ações que não estejam na lista."
    )

    client, model = _get_chat_client_and_model(settings, provider)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    if provider.strip().lower() == "groq":
        completion = client.chat.completions.create(
            model=model,
            temperature=0.2,
            max_completion_tokens=2048,
            top_p=0.95,
            reasoning_effort="none",
            messages=messages,
        )
    else:
        completion = client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=messages,
        )

    answer = completion.choices[0].message.content or "Nao consegui gerar a sugestão."
    answer = re.sub(r"(?s)<think>.*?</think>\s*", "", answer).strip() or answer
    return answer, sources


def _answer_recommendation_question(
    question: str, settings: Settings
) -> tuple[str, list[str]] | None:
    if not _looks_like_recommendation_question(question):
        return None

    question_tokens = _meaningful_tokens(question)
    if not question_tokens:
        return (
            "Me diga o tema, competência ou público-alvo desejado para eu sugerir ações do cadastro.",
            [],
        )

    rows = fetch_table_rows(settings)
    if not rows:
        return ("Nao encontrei registros no banco para sugerir ações.", [])

    wants_trail = "trilha" in _normalize_text(question) or "trilhas" in _normalize_text(question)
    field_weights = [
        ("Objetivo de Aprendizagem MCN", "objetivo de aprendizagem", 3.0),
        ("11. Objetivos Específicos", "objetivos específicos", 3.0),
        ("Competência MCN", "competência MCN", 2.6),
        ("10. Competência", "competência", 2.6),
        ("Eixo Funcional MCN", "eixo funcional", 2.0),
        ("6. Eixo", "eixo", 2.0),
        ("5. Público-Alvo", "público-alvo", 1.8),
        ("4. Tipo da Ação", "tipo da ação", 1.4),
        ("3. Nome da Ação", "nome da ação", 1.2),
        ("15. Conteúdos", "conteúdos", 1.0),
    ]
    ae_title_lookup = _build_ae_title_lookup(rows)

    scored_rows: list[tuple[float, dict, list[str]]] = []
    for row in rows:
        total_score = 0.0
        matched_fields: list[str] = []

        for column, label, weight in field_weights:
            score, matched_tokens = _score_weighted_field(
                question_tokens, _row_value(row, column, label), weight
            )
            if score > 0:
                total_score += score
                matched_fields.append(label)

        if wants_trail and _normalize_text(_row_value(row, "É Trilha?", "É Trilha?")) == "sim":
            total_score += 0.8
            matched_fields.append("trilha")

        if total_score > 0:
            scored_rows.append((total_score, row, matched_fields))

    scored_rows.sort(key=lambda item: item[0], reverse=True)
    if wants_trail:
        trail_rows = [
            item
            for item in scored_rows
            if _normalize_text(_row_value(item[1], "É Trilha?", "É Trilha?")) == "sim"
        ]
        top_rows = (trail_rows or scored_rows)[:5]
    else:
        top_rows = scored_rows[:5]

    if not top_rows:
        return (
            "Nao encontrei ações aderentes ao tema informado nos campos de objetivo, competência, eixo, público-alvo e tipologia.",
            [],
        )

    lines = [
        "Sugestões de ações do cadastro, priorizando objetivo, competências, eixo, público-alvo e tipologia:"
    ]
    sources: list[str] = []

    for score, row, matched_fields in top_rows:
        ae_id = _row_value(row, "ID AE", "ID AE") or str(row.get("cadastro") or row.get("id") or "")
        title = _row_value(row, "3. Nome da Ação", "3. Nome da Ação") or str(row.get("titulo") or "")
        action_type = _row_value(row, "4. Tipo da Ação", "4. Tipo da Ação")
        axis = _row_value(row, "6. Eixo", "6. Eixo") or _row_value(row, "Eixo Funcional MCN", "Eixo Funcional MCN")
        modules = _row_value(row, "Módulos Associados", "Módulos Associados")
        reason = _format_recommendation_reason(matched_fields)
        details = []
        if action_type:
            details.append(f"tipo: {action_type}")
        if axis:
            details.append(f"eixo: {axis}")

        suffix = f" ({'; '.join(details)})" if details else ""
        lines.append(f"- {ae_id}: {title}{suffix}. Motivo: {reason}.")
        if modules:
            lines.append("  Ações educativas associadas:")
            lines.extend(_format_associated_modules(modules, ae_title_lookup))
        sources.append(f"{settings.target_table}:{row.get('id', ae_id or 'sem_id')}")

    return "\n".join(lines), sources


def _looks_like_presential_question(question: str) -> bool:
    normalized = _normalize_text(question)
    if "presencial" not in normalized and "presenciais" not in normalized:
        return False
    return any(
        term in normalized
        for term in [
            "curso",
            "cursos",
            "acao",
            "acoes",
            "modalidade",
            "oferta",
            "ofertas",
        ]
    )


def _answer_presential_question(
    question: str, settings: Settings
) -> tuple[str, list[str]] | None:
    if not _looks_like_presential_question(question):
        return None

    rows = fetch_table_rows(settings)
    if not rows:
        return ("Nao encontrei registros no banco para avaliar cursos presenciais.", [])

    first_row = rows[0]
    modality_col = _find_row_column(first_row, "12. Modalidade")
    title_col = _find_row_column(first_row, "3. Nome da Ação") or "titulo"
    ae_id_col = _find_row_column(first_row, "ID AE") or "cadastro"

    exact_presential: list[dict] = []
    hybrid_with_presential: list[dict] = []

    for row in rows:
        if modality_col:
            modality = str(row.get(modality_col) or "").strip()
        else:
            modality = _extract_content_value(str(row.get("conteudo") or ""), "12. Modalidade")

        normalized_modality = _normalize_text(modality).strip(" .;")
        if normalized_modality == "presencial":
            exact_presential.append(row)
        elif "presencial" in normalized_modality:
            hybrid_with_presential.append(row)

    examples = exact_presential[:10]
    example_lines = []
    for row in examples:
        ae_id = str(row.get(ae_id_col) or row.get("cadastro") or row.get("id") or "").strip()
        title = str(row.get(title_col) or row.get("titulo") or "").strip()
        if ae_id and title:
            example_lines.append(f"- {ae_id}: {title}")

    answer_parts = [
        f"Sim. Encontrei {len(exact_presential)} ações com modalidade presencial no banco."
    ]
    if hybrid_with_presential:
        answer_parts.append(
            f"Também encontrei {len(hybrid_with_presential)} ação(ões) híbrida(s) que mencionam presencial."
        )
    if example_lines:
        answer_parts.append("Exemplos:\n" + "\n".join(example_lines))

    sources = [
        f"{settings.target_table}:{row.get('id', row.get(ae_id_col, 'sem_id'))}"
        for row in exact_presential[:20]
    ]
    return "\n\n".join(answer_parts), sources


def _get_chat_client_and_model(settings: Settings, provider: str):
    provider_normalized = provider.strip().lower()

    if provider_normalized == "groq":
        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY nao configurada.")
        return Groq(api_key=settings.groq_api_key), settings.groq_model

    if provider_normalized == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY nao configurada.")
        return OpenAI(api_key=settings.openai_api_key), settings.openai_model

    raise ValueError(f"Provedor de LLM invalido: {provider}")


def build_index(settings: Settings) -> int:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY nao configurada.")

    rows = fetch_rows(settings)
    docs: list[dict] = []
    for row in rows:
        text = _row_to_text(row, settings.target_text_columns)
        if not text:
            continue
        docs.append(
            {
                "id": str(row.get(settings.target_id_column, "sem_id")),
                "text": text,
            }
        )

    client = OpenAI(api_key=settings.openai_api_key)
    embeddings = _embed_texts(
        client, settings.openai_embedding_model, [doc["text"] for doc in docs]
    )

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(
        json.dumps({"docs": docs, "embeddings": embeddings}, ensure_ascii=True),
        encoding="utf-8",
    )
    return len(docs)


def _load_index() -> dict:
    if not INDEX_PATH.exists():
        raise FileNotFoundError(
            "Indice vetorial nao encontrado. Rode o endpoint POST /api/index primeiro."
        )
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    denominator = norm_a * norm_b
    if denominator == 0:
        return 0.0
    return dot_product / denominator


def _document_relevance(question: str, doc_text: str, embedding_score: float) -> float:
    question_lower = question.lower()
    doc_lower = doc_text.lower()
    question_tokens = _tokenize(question)
    doc_tokens = _tokenize(doc_text)

    overlap_score = len(question_tokens & doc_tokens) / max(1, len(question_tokens))
    score = (embedding_score * 0.7) + (overlap_score * 0.3)

    if "presencial" in question_lower:
        if "modalidade: presencial" in doc_lower:
            score += 0.45
        elif "hibrido" in doc_lower or "híbrido" in doc_lower:
            score += 0.20

    if "policiais penais" in question_lower:
        if "policiais penais" in doc_lower:
            score += 0.30
        if "público-alvo" in doc_lower or "publico-alvo" in doc_lower:
            score += 0.10

    if "educativas" in question_lower and (
        "educação" in doc_lower or "didática" in doc_lower or "instrutoria" in doc_lower
    ):
        score += 0.15

    return score


def _retrieve_context_by_embeddings(
    question: str, settings: Settings, index_data: dict
) -> tuple[list[dict], list[str]]:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY nao configurada.")

    docs = index_data["docs"]
    embeddings: list[list[float]] = index_data["embeddings"]

    client = OpenAI(api_key=settings.openai_api_key)
    question_embedding = (
        client.embeddings.create(model=settings.openai_embedding_model, input=question)
        .data[0]
        .embedding
    )
    question_vector = list(question_embedding)

    scored: list[tuple[float, int]] = []
    for idx, emb in enumerate(embeddings):
        doc_text = str(docs[idx].get("text", ""))
        embedding_score = _cosine_similarity(question_vector, emb)
        scored.append((_document_relevance(question, doc_text, embedding_score), idx))

    scored.sort(key=lambda item: item[0], reverse=True)
    top_items = scored[: settings.top_k]

    selected_docs = [docs[idx] for _, idx in top_items]
    selected_sources = [f"{settings.target_table}:{doc['id']}" for doc in selected_docs]
    return selected_docs, selected_sources


def _compact_doc_text(text: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max(0, max_chars - 3)].rstrip() + "..."


def _build_context_text(
    question: str, selected_docs: list[dict], settings: Settings
) -> str:
    question_tokens = _tokenize(question)
    limited_docs = selected_docs[: max(1, settings.max_context_docs)]

    sections: list[str] = []
    total_chars = 0

    for doc in limited_docs:
        doc_text = str(doc.get("text", ""))
        if not doc_text.strip():
            continue

        doc_tokens = _tokenize(doc_text)
        if question_tokens:
            overlap = len(question_tokens & doc_tokens)
            if overlap == 0 and sections:
                continue

        compact_text = _compact_doc_text(doc_text, settings.max_doc_chars)
        section = f"ID: {doc.get('id', 'sem_id')}\n{compact_text}"

        if sections:
            projected = total_chars + len(section) + 8
            if projected > settings.max_context_chars:
                break

        sections.append(section)
        total_chars += len(section)
        if total_chars >= settings.max_context_chars:
            break

    return "\n\n---\n\n".join(sections)


def retrieve_context(
    question: str, settings: Settings, provider: str = "openai"
) -> tuple[list[dict], list[str]]:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY nao configurada.")

    index_data = _load_index()
    if not index_data.get("embeddings"):
        build_index(settings)
        index_data = _load_index()

    return _retrieve_context_by_embeddings(question, settings, index_data)


def answer_question(
    question: str, settings: Settings, provider: str = "openai"
) -> tuple[str, list[str]]:
    recommendation_answer = _answer_recommendation_question(question, settings)
    if recommendation_answer:
        return recommendation_answer

    structured_answer = _answer_presential_question(question, settings)
    if structured_answer:
        return structured_answer

    selected_docs, sources = retrieve_context(question, settings, provider)
    context_text = _build_context_text(question, selected_docs, settings)

    system_prompt = (
        "Você é um assistente que responde usando apenas o contexto fornecido. "
        "Se o contexto não tiver dados suficientes, diga claramente que não encontrou no banco."
    )

    user_prompt = (
        f"Pergunta do usuario:\n{question}\n\n"
        f"Contexto recuperado do banco:\n{context_text}\n\n"
        "Responda em portugues e de forma objetiva."
    )

    client, model = _get_chat_client_and_model(settings, provider)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    if provider.strip().lower() == "groq":
        completion = client.chat.completions.create(
            model=model,
            temperature=0.2,
            max_completion_tokens=4096,
            top_p=0.95,
            reasoning_effort="none",
            messages=messages,
        )
    else:
        completion = client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=messages,
        )

    answer = completion.choices[0].message.content or "Nao consegui gerar resposta."
    answer = re.sub(r"(?s)<think>.*?</think>\s*", "", answer).strip() or answer
    return answer, sources
