"""Signed-transaction path (the one production uses), chain-id guard, confirmations, production config rules."""
import pytest
from eth_account import Account
from web3 import EthereumTesterProvider, Web3

from app.blockchain import service as chain
from app.config import Settings, settings
from app.database import SessionLocal
from app.models.models import BlockchainRecord
from test_04_blockchain_resilience import _pending_record, _rec


def test_signed_key_path_anchors_from_the_registrar_account(client, world, H, published, eth, monkeypatch):
    w3, contract = eth
    registrar = Account.create()
    w3.eth.send_transaction({"from": w3.eth.accounts[0], "to": registrar.address, "value": Web3.to_wei(1, "ether")})
    art = chain.load_artifact()                               # the deployer is the contract's registrar: deploy FROM the key
    tx = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"]).constructor().build_transaction(
        {"from": registrar.address, "nonce": 0, "chainId": w3.eth.chain_id})
    addr = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(registrar.sign_transaction(tx).raw_transaction)).contractAddress
    contract = w3.eth.contract(address=addr, abi=art["abi"])
    rec0 = _pending_record(client, H, published)
    chain.set_test_chain(w3, contract, registrar)
    db = SessionLocal()
    rec = chain.try_anchor(db, _rec(db, rec0["record_ref"]))
    assert rec.status == "anchored", rec.error_message
    tx = w3.eth.get_transaction(rec.transaction_hash)
    assert tx["from"] == registrar.address                    # signed locally, not an unlocked node account


def test_unfunded_registrar_leaves_record_pending_not_anchored(client, world, H, published, eth):
    w3, contract = eth
    rec0 = _pending_record(client, H, published)
    chain.set_test_chain(w3, contract, Account.create())     # zero balance and not the registrar
    db = SessionLocal()
    rec = chain.try_anchor(db, _rec(db, rec0["record_ref"]))
    assert rec.status in ("pending", "failed") and rec.status != "anchored"
    assert contract.functions.totalAnchored().call() == 0


def test_chain_id_guard(monkeypatch):
    w3 = Web3(EthereumTesterProvider())
    monkeypatch.setattr(settings, "BLOCKCHAIN_EXPECTED_CHAIN_ID", 0)
    chain._check_chain_id(w3)                                 # unset => not checked
    monkeypatch.setattr(settings, "BLOCKCHAIN_EXPECTED_CHAIN_ID", w3.eth.chain_id)
    chain._check_chain_id(w3)
    monkeypatch.setattr(settings, "BLOCKCHAIN_EXPECTED_CHAIN_ID", 11155111)
    with pytest.raises(RuntimeError, match="Refusing to use this node"):
        chain._check_chain_id(w3)


def test_confirmations_wait_for_depth(monkeypatch):
    w3 = Web3(EthereumTesterProvider())
    monkeypatch.setattr(settings, "BLOCKCHAIN_CONFIRMATIONS", 2)
    monkeypatch.setattr(chain.time, "sleep", lambda s: w3.provider.ethereum_tester.mine_blocks(1))
    h = w3.eth.send_transaction({"from": w3.eth.accounts[0], "to": w3.eth.accounts[1], "value": 1})
    r = w3.eth.wait_for_transaction_receipt(h)
    chain._wait_confirmations(w3, r)
    assert w3.eth.block_number - r.blockNumber >= 2
    monkeypatch.setattr(chain.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="confirmations"):
        chain._wait_confirmations(w3, type("R", (), {"blockNumber": w3.eth.block_number + 50})(), timeout=0)


def _prod(**kw):
    base = dict(ENVIRONMENT="production", BLOCKCHAIN_ENABLED=True, BLOCKCHAIN_RPC_URL="https://rpc.example.org",
                BLOCKCHAIN_EXPECTED_CHAIN_ID=11155111, BLOCKCHAIN_PRIVATE_KEY="ab" * 32)
    base.update(kw)
    return Settings(_env_file=None, **base)


def _problems(s):
    try:
        s.validate_for_startup()
        return []
    except Exception as exc:
        return [str(exc)]


def test_production_requires_chain_id_and_registrar_key():
    msg = " ".join(_problems(_prod(BLOCKCHAIN_EXPECTED_CHAIN_ID=0)))
    assert "BLOCKCHAIN_EXPECTED_CHAIN_ID" in msg
    msg = " ".join(_problems(_prod(BLOCKCHAIN_PRIVATE_KEY="")))
    assert "BLOCKCHAIN_PRIVATE_KEY" in msg
    msg = " ".join(_problems(_prod(BLOCKCHAIN_CONFIRMATIONS=500)))
    assert "BLOCKCHAIN_CONFIRMATIONS" in msg
