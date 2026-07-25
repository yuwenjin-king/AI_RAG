"""OpenTelemetry 分布式追踪封装（plan_three §3）。

优雅降级：未安装 opentelemetry 时，span() 为 no-op，应用正常运行（仅不产生 span）。
安装后按 OTEL_EXPORTER 导出（console | otlp）。业务关键路径手动埋点 span，
补全 metrics（聚合）之外的 trace（定位慢段/失败段）。
"""
from __future__ import annotations

import contextlib
from typing import Any, Iterator, Optional

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_tracer: Optional[Any] = None  # opentelemetry.trace.Tracer
_provider: Optional[Any] = None  # TracerProvider
_available: bool = False

try:  # 核心依赖；缺失则整体降级为 no-op（不阻断应用）
    from opentelemetry import trace as _trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    _OTEL_OK = True
except ImportError:  # pragma: no cover - 取决于运行环境是否装了 otel
    _OTEL_OK = False
    _trace = None  # type: ignore[assignment]
    Resource = None  # type: ignore[assignment]
    TracerProvider = None  # type: ignore[assignment]
    BatchSpanProcessor = None  # type: ignore[assignment]
    ConsoleSpanExporter = None  # type: ignore[assignment]


def is_available() -> bool:
    return _available


def _make_otlp_processor():  # type: ignore[no-untyped-def]
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_endpoint))  # type: ignore[misc]
    except ImportError:
        log.warning("tracing.otlp_exporter_missing fallback_console")
        return BatchSpanProcessor(ConsoleSpanExporter())  # type: ignore[misc]


def init_tracing() -> None:
    """初始化 TracerProvider + 导出器。未启用或未安装 OTel → no-op。"""
    global _tracer, _provider, _available
    if _available:
        return
    if not settings.otel_enabled or not _OTEL_OK:
        log.info("tracing.disabled (enabled=%s installed=%s)", settings.otel_enabled, _OTEL_OK)
        return

    resource = Resource.create({"service.name": settings.otel_service_name})  # type: ignore[union-attr]
    provider = TracerProvider(resource=resource)  # type: ignore[misc]
    exporter = (settings.otel_exporter or "console").lower()
    if exporter == "otlp":
        processor = _make_otlp_processor()
    else:
        processor = BatchSpanProcessor(ConsoleSpanExporter())  # type: ignore[misc]
        exporter = "console"

    provider.add_span_processor(processor)  # type: ignore[union-attr]
    _trace.set_tracer_provider(provider)  # type: ignore[union-attr]
    _provider = provider
    _tracer = _trace.get_tracer(settings.otel_service_name)  # type: ignore[union-attr]
    _available = True
    log.info("tracing.initialized exporter=%s service=%s", exporter, settings.otel_service_name)


def shutdown_tracing() -> None:
    global _provider, _available
    if _provider is not None:
        try:
            _provider.shutdown()
        except Exception as e:  # noqa: BLE001
            log.warning("tracing.shutdown.err=%s", e)
        _provider = None
        _available = False


@contextlib.contextmanager
def span(name: str, **attrs: Any) -> Iterator[Optional[Any]]:
    """业务 span。无 OTel / 未启用 → no-op（仅执行代码块，不产生 span）。"""
    if not _available or _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as s:
        for k, v in attrs.items():
            try:
                s.set_attribute(k, v)
            except Exception:  # noqa: BLE001
                pass
        yield s


def get_tracer() -> Optional[Any]:
    """暴露 tracer，供需直接操作（设置 status/error 等）的调用方使用。"""
    return _tracer
