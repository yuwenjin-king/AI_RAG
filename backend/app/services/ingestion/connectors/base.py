"""连接器抽象（设计书 §4.1）。

内置：文件系统 / 对象存储（真实）；DB / Wiki / API 为接口 + stub。
新数据源实现 Connector 接口即可插件化接入。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional


@dataclass
class ChangeEvent:
    """数据源变更事件。"""

    source: str            # 连接器标识
    object_key: str        # 原始对象键 / 主键
    title: str
    content_type: str = "application/octet-stream"
    size_bytes: int = 0
    checksum: Optional[str] = None
    meta: Optional[dict] = None


class Connector(ABC):
    """连接器接口：拉取 + 变更感知。"""

    name: str = "base"

    @abstractmethod
    async def scan(self) -> AsyncIterator[ChangeEvent]:
        """全量扫描，产出变更事件。"""
        ...
        yield ChangeEvent(source=self.name, object_key="", title="")  # pragma: no cover

    async def poll_changes(self) -> AsyncIterator[ChangeEvent]:
        """增量变更（默认走全量，具体连接器可重写为 CDC/hash 差量）。"""
        async for ev in self.scan():
            yield ev

    async def fetch_bytes(self, event: ChangeEvent) -> bytes:
        raise NotImplementedError
