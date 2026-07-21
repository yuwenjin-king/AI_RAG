"""统一异常体系。"""
from __future__ import annotations


class AppError(Exception):
    """业务异常基类。status_code 与 code 供全局处理器映射。"""

    status_code: int = 400
    code: str = "app_error"

    def __init__(self, message: str = "", *, code: str | None = None, status_code: int | None = None):
        super().__init__(message or self.code)
        self.message = message or self.code
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class UpstreamError(AppError):
    status_code = 502
    code = "upstream_error"


class DegradedError(AppError):
    """降级仍可返回结果时用，仅用于标记，不抛到客户端为错误。"""

    status_code = 200
    code = "degraded"
