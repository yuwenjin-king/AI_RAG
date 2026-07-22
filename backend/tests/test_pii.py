from app.services.ingestion import pii


def test_mask_disabled_passthrough(monkeypatch):
    monkeypatch.setattr(pii.settings, "pii_masking_enabled", False)
    assert pii.mask("call 13812345678") == "call 13812345678"


def test_mask_all_rules(monkeypatch):
    monkeypatch.setattr(pii.settings, "pii_masking_enabled", True)
    monkeypatch.setattr(pii.settings, "pii_rules", "phone,email,idcard,bank")
    out = pii.mask("手机13812345678 邮箱 ab.cd@example.com 身份证110101199003077734 卡6222020200011111111")
    assert "138****5678" in out
    assert "ab.cd@" not in out and "***@example.com" in out
    assert "110101********7734" in out
    assert "6222***********1111" in out
    # 原始明文不得残留
    assert "13812345678" not in out
    assert "110101199003077734" not in out


def test_mask_idcard_before_bank(monkeypatch):
    # 18 位身份证不应被银行卡规则二次处理
    monkeypatch.setattr(pii.settings, "pii_masking_enabled", True)
    monkeypatch.setattr(pii.settings, "pii_rules", "bank,idcard")
    out = pii.mask("id 110101199003077734")
    assert "****" in out and "110101199003077734" not in out


def test_mask_doc(monkeypatch):
    from app.services.knowledge.block import Block, ParsedDoc

    monkeypatch.setattr(pii.settings, "pii_masking_enabled", True)
    monkeypatch.setattr(pii.settings, "pii_rules", "phone")
    doc = ParsedDoc(title="13800001111", blocks=[Block(text="电话13812345678")])
    pii.mask_doc(doc)
    assert doc.title == "138****1111"
    assert doc.blocks[0].text == "电话138****5678"


def test_mask_keeps_non_pii(monkeypatch):
    monkeypatch.setattr(pii.settings, "pii_masking_enabled", True)
    monkeypatch.setattr(pii.settings, "pii_rules", "phone,email,idcard,bank")
    assert pii.mask("订单号 ABC-2026-0001 金额 99.50") == "订单号 ABC-2026-0001 金额 99.50"
