from __future__ import annotations

import csv
import sqlite3
import unicodedata
from pathlib import Path

CSV_PATH = Path("CADASTRO_UNICO_AE_CONSOLIDADO_simplificado - consolidado.csv")
SQLITE_PATH = Path("data/local.db")
TABLE_NAME = "rag_docs"
EXPECTED_COLUMNS = [
    "Estado",
    "Sigla Estado",
    "ID AE",
    "É Trilha?",
    "É Módulo?",
    "Módulos Associados",
    "Competência MCN",
    "Eixo Funcional MCN",
    "Unidade Temática MCN",
    "Conhecimento Crítico e para a Prática",
    "Objetivo de Aprendizagem MCN",
    "1. Área Demandante",
    "2. Escola Proponente",
    "3. Nome da Ação",
    "4. Tipo da Ação",
    "5. Público-Alvo",
    "6. Eixo",
    "7. Unidade",
    "8. Justificativa da Oferta",
    "9. Amparo Legal",
    "10. Competência",
    "11. Objetivos Específicos",
    "12. Modalidade",
    "13. Carga Horária",
    "14. Duração",
    "15. Conteúdos",
    "16. Metodologia de Ensino",
    "17. Espaço Físico",
    "18. Plataforma Virtual de Ensino e Aprendizagem",
    "19. Recursos Materiais",
    "20. Recursos Tecnológicos",
    "21. Recursos Humanos",
    "22. Instrumentos de Avaliação de Aprendizagem",
    "23. Instrumentos de Avaliação de Reação",
    "24. Instrumentos de Avaliação de Transferência e Impacto",
    "25. Critérios de Matrícula",
    "26. Critérios de Certificação",
    "27. Bibliografia",
]


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(value.lower().strip().split())


def _read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return []

        parsed_rows: list[dict[str, str]] = []
        for row in reader:
            row_dict = {
                (key.strip() if key else ""): ("" if value is None else str(value).strip())
                for key, value in row.items()
                if key
            }
            if any(row_dict.values()):
                parsed_rows.append(row_dict)
        return parsed_rows


def _pick_column(columns: list[str], candidates: list[str], default: str) -> str:
    normalized = {_normalize(col): col for col in columns}
    for cand in candidates:
        normalized_cand = _normalize(cand)
        if normalized_cand in normalized:
            return normalized[normalized_cand]
    for col in columns:
        col_low = _normalize(col)
        if any(_normalize(cand) in col_low for cand in candidates):
            return col
    return default


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def main() -> None:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Arquivo CSV nao encontrado: {CSV_PATH}")

    rows = _read_rows(CSV_PATH)
    if not rows:
        raise ValueError("CSV sem linhas de dados.")

    columns = list(rows[0].keys())
    missing_columns = [col for col in EXPECTED_COLUMNS if col not in columns]
    extra_columns = [col for col in columns if col not in EXPECTED_COLUMNS]
    if missing_columns or extra_columns:
        raise ValueError(
            "Cabecalho do CSV diferente do esperado. "
            f"Colunas faltantes: {missing_columns}. Colunas extras: {extra_columns}."
        )

    title_col = _pick_column(
        columns,
        ["3. nome da ação", "3. nome da acao", "nome da ação", "nome da acao", "nome"],
        columns[0],
    )
    cadastro_col = _pick_column(columns, ["id ae", "cadastro", "codigo", "id"], columns[1])

    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(SQLITE_PATH)

    try:
        cursor = connection.cursor()
        cursor.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
        csv_column_definitions = ",\n                ".join(
            f"{_quote_identifier(col)} TEXT" for col in columns
        )
        cursor.execute(
            f"""
            CREATE TABLE {TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_row INTEGER NOT NULL,
                titulo TEXT,
                cadastro TEXT,
                conteudo TEXT NOT NULL,
                {csv_column_definitions}
            )
            """
        )

        insert_columns = ["source_row", "titulo", "cadastro", "conteudo", *columns]
        quoted_insert_columns = ", ".join(
            _quote_identifier(col) for col in insert_columns
        )
        placeholders = ", ".join("?" for _ in insert_columns)

        for idx, row in enumerate(rows, start=1):
            titulo = row.get(title_col, "")
            cadastro = row.get(cadastro_col, "")
            conteudo = "\n".join(
                [f"{col}: {value}" for col, value in row.items() if value]
            )
            values = [idx, titulo, cadastro, conteudo, *[row.get(col, "") for col in columns]]
            cursor.execute(
                f"INSERT INTO {TABLE_NAME} ({quoted_insert_columns}) VALUES ({placeholders})",
                values,
            )

        connection.commit()
        print(
            f"SQLite criado em {SQLITE_PATH} com {len(rows)} linhas a partir de {CSV_PATH}."
        )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
