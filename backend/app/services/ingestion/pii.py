"""PII 脱敏（设计书 §8）：接入阶段识别并掩码敏感信息。

规则（正则，按优先级顺序应用，避免重叠误伤）：
  idcard（身份证 18 位）→ phone（手机 11 位）→ email → bank（银行卡 16/19 位）
开关由 settings.pii_masking_enabled / pii_rules 控制；脱敏在解析后、入库前进行，
保证 PII 不进入 chunk / 索引。可选接入 presidio 做更强识别（按需）。
"""
from __future__ import annotations

import re
from typing import Iterable

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


def _mask_phone(m: re.Match) -> str:
    s = m.group(0)
    return s[:3] + "****" + s[-4:]


def _mask_email(m: re.Match) -> str:
    local, _, domain = m.group(0).partition("@")
    if not local or not domain:
        return m.group(0)
    return local[:1] + "***@" + domain


def _mask_idcard(m: re.Match) -> str:
    s = m.group(0)
    return s[:6] + "********" + s[-4:]


def _mask_bank(m: re.Match) -> str:
    s = m.group(0)
    return s[:4] + "*" * (len(s) - 8) + s[-4:]


# 顺序敏感：idcard 先于 bank，避免 18 位身份证被当银行卡
_RULES = {
    "idcard": (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), _mask_idcard),
    "phone": (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), _mask_phone),
    "email": (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), _mask_email),
    "bank": (re.compile(r"(?<!\d)\d{16}(?:\d{2,3})?(?!\d)"), _mask_bank),
}


def enabled_rules(raw: str | None = None) -> list[str]:
    raw = raw if raw is not None else settings.pii_rules
    names = [r.strip().lower() for r in (raw or "").split(",") if r.strip()]
    return [r for r in names if r in _RULES]


def mask(text: str, rules: Iterable[str] | None = None) -> str:
    """对文本按启用规则脱敏。rules=None 时取 settings 配置；未启用则原样返回。"""
    if not text:
        return text
    active = list(rules) if rules is not None else (
        enabled_rules() if settings.pii_masking_enabled else []
    )
    out = text
    for name in active:
        pat, fn = _RULES[name]
        out = pat.sub(fn, out)
    return out


def mask_doc(doc) -> "doc":
    """对 ParsedDoc 的 block 文本与标题脱敏（未启用则原样返回）。"""
    from app.services.knowledge.block import ParsedDoc  # noqa: F811

    if not settings.pii_masking_enabled or not isinstance(doc, ParsedDoc):
        return doc
    for b in doc.blocks:
        b.text = mask(b.text)
    if doc.title:
        doc.title = mask(doc.title)
    return doc
