from types import SimpleNamespace
from app.config import settings
from app.security.ratelimit import client_ip


def _req(xff=None, peer="10.0.0.5"):
    h = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=h)


def test_header_ignored_by_default_so_it_cannot_be_forged(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 0)
    assert client_ip(_req("1.2.3.4")) == "10.0.0.5"


def test_one_trusted_proxy_uses_last_entry_not_client_supplied_prefix(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
    assert client_ip(_req("6.6.6.6, 203.0.113.9")) == "203.0.113.9"      # attacker-prepended 6.6.6.6 is ignored
    assert client_ip(_req(None)) == "10.0.0.5"                          # no header -> peer
