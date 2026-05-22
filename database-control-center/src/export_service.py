from __future__ import annotations

from io import BytesIO

import pandas as pd
from sqlalchemy import select
from sqlalchemy.engine import Engine

from src.schema_inspector import reflect_table


def dataframe_to_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8")


def dataframe_to_excel_bytes(frame: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="data")
    output.seek(0)
    return output.read()


def export_table_to_dataframe(engine: Engine, table_name: str) -> pd.DataFrame:
    table = reflect_table(engine, table_name)
    with engine.connect() as connection:
        return pd.read_sql(select(table), connection)
