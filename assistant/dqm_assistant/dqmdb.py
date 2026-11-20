"""Small helpers over DJ's dqm.reader (Query Engine), shared by histsource and dqm_alarms."""

from __future__ import annotations

from typing import Sequence


def id_range(column: str, ids: Sequence[int]):
    """Query Engine has no IN: a bounding range; the caller filters exact membership after."""
    from dqm.reader.transport import where
    return [where(column, "ge", min(ids)), where(column, "le", max(ids))]


def rows_for_ids(reader, table: str, column: str, ids):
    ids = set(int(i) for i in ids)
    df = reader.read_table(table, clauses=id_range(column, sorted(ids)), limit=None)
    return df[df[column].isin(ids)]
