import base64
import copy

import pytest
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from x402m.core import private_er as P
from x402m.types.config import DEVNET, MAINNET

E_TOKEN = Pubkey.from_string(P.EPHEMERAL_SPL_PROGRAM)
MEMO = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")
TOKEN = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
OWNER = Keypair()  # test wallet standing in for the owner; never a messaging key
RECIPIENT = str(Pubkey.new_unique())
VALIDATOR = str(Pubkey.new_unique())
NONCE = "11" * 32
URL = "https://merchant.example/api/report"
COMMIT = P.resource_commitment(URL, NONCE)


def _tx(*programs, sign=True):
    ixs = [Instruction(p, b"\x19\x00", [AccountMeta(OWNER.pubkey(), True, True)]) for p in programs]
    msg = MessageV0.try_compile(OWNER.pubkey(), ixs, [], Hash.default())
    tx = VersionedTransaction(msg, [OWNER]) if sign else VersionedTransaction.populate(msg, [Signature.default()])
    return base64.b64encode(bytes(tx)).decode()


def _signature_placeholder():
    return "5" * 87 + "1"


def sealed(route="ephemeral-to-ephemeral", **extra_overrides):
    extra = {
        "cluster": "devnet-private", "programId": P.EPHEMERAL_SPL_PROGRAM, "validator": VALIDATOR,
        "route": route, "minDelayMs": "0", "maxDelayMs": "30000", "split": 3,
        "resourceCommitment": COMMIT, "receipt": "settlement-only",
        "disclosure": list(P.REQUIRED_DISCLOSURE[route]),
    }
    pay_to = RECIPIENT
    if route == "base-to-stealth":
        extra["recipientHandle"] = "alice@musebook.trade"
        pay_to = P.stealth_pool_pda("alice@musebook.trade")
    else:
        extra["recipient"] = RECIPIENT
    extra.update(extra_overrides)
    return {"scheme": P.SEALED_SCHEME, "network": DEVNET, "amount": "1000", "asset": P.DEVNET_USDC,
            "payTo": pay_to, "maxTimeoutSeconds": 60, "extra": extra}


def magicblock(cluster="devnet-private"):
    return {"scheme": "exact-magicblock", "network": DEVNET, "amount": "1000000", "asset": P.DEVNET_USDC,
            "payTo": RECIPIENT, "maxTimeoutSeconds": 60,
            "extra": {"paymentId": "pay_1", "merchantId": RECIPIENT, "payer": str(OWNER.pubkey()),
                      "cluster": cluster, "validator": VALIDATOR, "settlement": "ephemeral-rollup",
                      "assetTransferMethod": "delegated-spl", "paymentFlow": "upfront"}}


def reason(fn, *args):
    with pytest.raises(P.PrivateErError) as err:
        fn(*args)
    return err.value.reason


# ── advertisement ──

LIVE_SUPPORTED = {"kinds": [{"x402Version": 2, "scheme": "exact", "network": DEVNET},
                            {"x402Version": 1, "scheme": "exact", "network": MAINNET}], "extensions": []}


def test_not_advertised_on_current_musebook_supported():
    assert not P.is_advertised(LIVE_SUPPORTED, P.SEALED_SCHEME)
    assert not P.is_advertised(LIVE_SUPPORTED, P.EXACT_MAGICBLOCK)
    assert P.is_advertised(LIVE_SUPPORTED, "exact")
    assert P.is_advertised({"kinds": [{"x402Version": 2, "scheme": P.SEALED_SCHEME, "network": DEVNET}]}, P.SEALED_SCHEME)
    assert not P.is_advertised({"kinds": [{"x402Version": 1, "scheme": P.SEALED_SCHEME, "network": DEVNET}]}, P.SEALED_SCHEME)
    assert not P.is_advertised(None, P.SEALED_SCHEME)


# ── exact-magicblock reference ──

def test_exact_magicblock_devnet_private_ok_and_not_sealed():
    assert P.validate_exact_magicblock(magicblock())["cluster"] == "devnet-private"
    profile = P.privacy_profile(magicblock())
    assert "amount" in profile["paymentServiceSees"] and "payer" in profile["settlementResponseIncludes"]
    assert not any(profile["darkX402"].values())
    assert "amount" in P.privacy_profile(magicblock("devnet"))["publicObserversSee"]


@pytest.mark.parametrize("mutate,expected", [
    (lambda r: r["extra"].update(cluster="mainnet-private"), "mainnet_disabled"),
    (lambda r: r.update(network=MAINNET), "mainnet_disabled"),
    (lambda r: r["extra"].update(cluster="devnet-tee"), "unsupported_cluster"),
    (lambda r: r.update(asset="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"), "unsupported_asset"),
    (lambda r: r["extra"].update(settlement="l1"), "invalid_settlement"),
    (lambda r: r.update(amount="0"), "invalid_amount"),
    (lambda r: r.update(scheme="exact"), "wrong_scheme"),
    (lambda r: r.update(bonus=1), "invalid_requirements"),
])
def test_exact_magicblock_rejections(mutate, expected):
    req = magicblock()
    mutate(req)
    assert reason(P.validate_exact_magicblock, req) == expected


# ── sealed requirements ──

def test_stealth_pool_pda_seed_layouts():
    short, mid, long = "a" * 32, "b" * 64, "c" * 255
    pdas = {P.stealth_pool_pda(h) for h in (short, mid, long)}
    assert len(pdas) == 3
    raw = long.encode()
    import hashlib
    expected = Pubkey.find_program_address([b"stealth_pool", raw[:32], hashlib.sha256(b"stealth_pool_handle" + raw).digest()], E_TOKEN)[0]
    assert P.stealth_pool_pda(long) == str(expected)
    assert P.stealth_pool_pda("Alice") != P.stealth_pool_pda("alice")  # no normalization
    assert reason(P.stealth_pool_pda, "") == "invalid_handle"
    assert reason(P.stealth_pool_pda, "x" * 256) == "invalid_handle"


@pytest.mark.parametrize("route", P.SEALED_ROUTES)
def test_sealed_requirements_valid(route):
    assert P.validate_sealed_requirements(sealed(route))["route"] == route


def test_privacy_profiles_are_honest():
    e2e = P.privacy_profile(sealed())
    assert e2e["darkX402"]["amountSealed"] and e2e["darkX402"]["endpointSealed"]
    assert e2e["darkX402"]["facilitatorBlind"] is False
    stealth = P.privacy_profile(sealed("base-to-stealth"))
    assert stealth["darkX402"]["amountSealed"] is False and stealth["darkX402"]["payerSealed"] is False
    assert "deposit amount" in stealth["publicObserversSee"]


@pytest.mark.parametrize("mutate,expected", [
    (lambda r: r.update(network=MAINNET), "mainnet_disabled"),
    (lambda r: r["extra"].update(cluster="mainnet-private"), "mainnet_disabled"),
    (lambda r: r["extra"].update(cluster="devnet"), "private_cluster_required"),
    (lambda r: r["extra"].update(programId=str(Pubkey.new_unique())), "invalid_program"),
    (lambda r: r["extra"].update(route="base-to-base"), "unsupported_route"),
    (lambda r: r["extra"].update(split=16), "invalid_split"),
    (lambda r: r["extra"].update(split=0), "invalid_split"),
    (lambda r: r["extra"].update(minDelayMs="5", maxDelayMs="4"), "invalid_delay"),
    (lambda r: r["extra"].update(maxDelayMs="2678400001"), "invalid_delay"),
    (lambda r: r["extra"].update(receipt="full"), "invalid_receipt_mode"),
    (lambda r: r["extra"].update(resourceCommitment="https://merchant.example"), "invalid_resource_commitment"),
    (lambda r: r["extra"]["disclosure"].pop(), "disclosure_mismatch"),
    (lambda r: r["extra"].update(memo="payment:1"), "invalid_extra"),
    (lambda r: r["extra"].update(recipientHandle="bob"), "recipient_required"),
    (lambda r: r.update(payTo=str(Pubkey.new_unique())), "pay_to_mismatch"),
    (lambda r: r.update(amount="18446744073709551616"), "invalid_amount"),
    (lambda r: r.update(maxTimeoutSeconds=601), "invalid_timeout"),
])
def test_sealed_requirement_rejections(mutate, expected):
    req = sealed()
    mutate(req)
    assert reason(P.validate_sealed_requirements, req) == expected


def test_stealth_route_rules():
    req = sealed("base-to-stealth")
    req["payTo"] = RECIPIENT
    assert reason(P.validate_sealed_requirements, req) == "pay_to_not_stealth_pool"
    req = sealed("base-to-stealth")
    req["extra"]["disclosure"] = list(P.REQUIRED_DISCLOSURE["ephemeral-to-ephemeral"])
    assert reason(P.validate_sealed_requirements, req) == "disclosure_mismatch"
    req = sealed("base-to-stealth", recipient=RECIPIENT)
    assert reason(P.validate_sealed_requirements, req) == "stealth_handle_required"


# ── sealed payload / transaction screen ──

def payload(tx=None, **inner):
    req = sealed()
    body = {"transaction": tx or _tx(E_TOKEN), "resourceCommitment": COMMIT}
    body.update(inner)
    return {"x402Version": 2, "accepted": copy.deepcopy(req), "payload": body}, req


def test_sealed_payload_ok():
    p, req = payload()
    assert P.validate_sealed_payload(p, req)["feePayer"] == str(OWNER.pubkey())
    assert P.verify_resource_binding(req, URL, NONCE)
    assert reason(P.verify_resource_binding, req, URL + "?x=1", NONCE) == "resource_commitment_mismatch"


@pytest.mark.parametrize("tx,expected", [
    (lambda: _tx(E_TOKEN, MEMO), "memo_leak"),
    (lambda: _tx(TOKEN), "plain_token_transfer"),
    (lambda: _tx(Pubkey.new_unique()), "missing_ephemeral_spl_instruction"),
    (lambda: _tx(E_TOKEN, sign=False), "unsigned_transaction"),
    (lambda: "not base64!", "invalid_transaction"),
    (lambda: "A" * 2000, "invalid_transaction"),
])
def test_sealed_transaction_screen(tx, expected):
    assert reason(P.check_sealed_transaction, tx()) == expected


def test_signature_from_wrong_key_rejected():
    raw = VersionedTransaction.from_bytes(base64.b64decode(_tx(E_TOKEN)))
    forged = VersionedTransaction.populate(raw.message, [Keypair().sign_message(bytes(raw.message))])
    assert reason(P.check_sealed_transaction, base64.b64encode(bytes(forged)).decode()) == "unsigned_transaction"


def test_sealed_payload_rejections():
    p, req = payload()
    p["resource"] = {"url": URL}
    assert reason(P.validate_sealed_payload, p, req) == "invalid_payload"  # endpoint must not travel in clear
    p, req = payload(agentKey="jwk")
    assert reason(P.validate_sealed_payload, p, req) == "agent_key_material"
    p, req = payload(resourceCommitment="00" * 32)
    assert reason(P.validate_sealed_payload, p, req) == "resource_commitment_mismatch"
    p, req = payload()
    p["accepted"]["amount"] = "1"
    assert reason(P.validate_sealed_payload, p, req) == "requirements_mismatch"
    p, req = payload()
    p["x402Version"] = 1
    assert reason(P.validate_sealed_payload, p, req) == "unsupported_version"


# ── settlement output ──

def test_settlement_only_response():
    req = sealed()
    body = P.sealed_settlement_response(_signature_placeholder(), req)
    assert P.assert_settlement_only(body)
    assert body["success"] and set(body) == {"success", "transaction", "network", "extensions"}
    pending = P.sealed_settlement_response(_signature_placeholder(), req, pending=True)
    assert pending["success"] is False and pending["errorReason"] == "settlement_pending"
    magicblock_style = {"success": True, "transaction": "x", "payer": "p", "amount": "1000", "network": DEVNET}
    assert reason(P.assert_settlement_only, magicblock_style) == "settlement_leak:amount,payer"
