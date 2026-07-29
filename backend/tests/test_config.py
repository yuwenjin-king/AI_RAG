"""配置测试：cors_origins 的 env 解析（防回归 plan_four §3 启动崩溃）。"""
from __future__ import annotations

from app.core.config import Settings


def test_cors_origins_list_from_comma_string(monkeypatch):
    """CORS_ORIGINS 逗号分隔串 → list（pydantic-settings 对 List 字段按 JSON 解析会崩，故用 str+属性）。"""
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
    s = Settings(_env_file=None)
    assert isinstance(s.cors_origins, str)
    assert s.cors_origins_list == ["http://localhost:5173", "http://localhost:3000"]


def test_cors_origins_list_single_value(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://prod.example.com")
    s = Settings(_env_file=None)
    assert s.cors_origins_list == ["https://prod.example.com"]


def test_cors_origins_default_when_unset(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    s = Settings(_env_file=None)
    assert "http://localhost:5173" in s.cors_origins_list
