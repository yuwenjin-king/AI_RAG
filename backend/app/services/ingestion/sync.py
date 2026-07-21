"""增量同步（设计书 §4.1）。

- 文件类数据源：基于 checksum/timestamp 差量比对
- 数据库类数据源：CDC 接口（Debezium 等）——首版为接口占位
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class DocFingerprint:
    object_key: str
    checksum: Optional[str]
    mtime: Optional[float]


class ChangeDetector(ABC):
    """变更检测接口。"""

    @abstractmethod
    def diff(self, seen: dict[str, DocFingerprint], current: list[DocFingerprint]) -> list[DocFingerprint]:
        ...


class HashTimestampDetector(ChangeDetector):
    """按 checksum（优先）/ mtime 判定新增或变更。"""

    def diff(self, seen: dict[str, DocFingerprint], current: list[DocFingerprint]) -> list[DocFingerprint]:
        out: list[DocFingerprint] = []
        for fp in current:
            old = seen.get(fp.object_key)
            if old is None:
                out.append(fp)
            elif fp.checksum and old.checksum and fp.checksum != old.checksum:
                out.append(fp)
            elif fp.mtime and old.mtime and fp.mtime > old.mtime:
                out.append(fp)
        return out


class CDCSource(ABC):
    """CDC 变更捕获接口（数据库类数据源）。接入 Debezium/Kafka Connect 时实现。"""

    @abstractmethod
    async def events(self):
        ...
