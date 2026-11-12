"""Private x402 on MagicBlock Ephemeral Rollups: wire checks only. No signing, no RPC.

Two profiles (see ``schemes/scheme_private_er_solana.md``):

* ``exact-magicblock`` is MagicBlock's own x402 v2 checkout scheme, defined in
  https://github.com/magicblock-labs/ephemeral-spl-token (``api/PAYMENTS.md``,
  ``api/src/payments/protocols.ts``). We only *check* its requirements here.
* ``musebook-sealed-er`` is our experimental v0 profile working toward the
  "Dark x402" properties described at https://dark.percolator.tech (payer,
  amount and endpoint sealed; only settlement comes out). It is not Dark x402,
  not a MagicBlock product and not advertised by any facilitator.

Every helper is devnet-only. Mainnet networks/clusters are rejected. Agent
(messaging) keys never appear here; the wallet owner signs the transaction.
"""
import base64
import binascii
import hashlib
import hmac
import json
import re

from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from ..types.config import DEVNET, MAINNET, USDC

EXACT_MAGICBLOCK = "exact-magicblock"
SEALED_SCHEME = "musebook-sealed-er"
SEALED_VERSION = "v0"
EPHEMERAL_SPL_PROGRAM = "SPLxh1LVZzEkX99H6rqYizhytLWPZVV296zyYDPagv2"
DEVNET_USDC = USDC[DEVNET]
MAGICBLOCK_CLUSTERS = {"devnet": DEVNET, "devnet-private": DEVNET}
MAINNET_CLUSTERS = {"mainnet", "mainnet-private"}
SEALED_ROUTES = ("ephemeral-to-ephemeral", "base-to-stealth")
MEMO_PROGRAMS = {"MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr", "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo"}
TOKEN_PROGRAMS = {"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"}
MAX_TX_BASE64 = 1644  # same bound as protocols.ts transactionSchema
MAX_SPLIT = 15
MAX_DELAY_MS = 2_678_400_000  # api PRIVATE_TRANSFER_MAX_DELAY_MS_LIMIT
U64_MAX = (1 << 64) - 1
REQUIREMENT_KEYS = {"scheme", "network", "amount", "asset", "payTo", "maxTimeoutSeconds", "extra"}
SEALED_EXTRA_KEYS = {"cluster", "programId", "validator", "route", "recipient", "recipientHandle",
                     "minDelayMs", "maxDelayMs", "split", "resourceCommitment", "receipt", "disclosure"}
SEALED_EXTRA_OPTIONAL = {"recipient", "recipientHandle"}
COMMITMENT_DOMAIN = b"musebook-sealed-er/v0/resource"

# What a v0 sealed payment still reveals, per route. Both sides must echo the
# exact list in ``extra.disclosure`` so nobody can claim more privacy than exists.
_COMMON_DISCLOSURE = (
    "tee-validator-sees-payment",      # Intel TDX operated by MagicBlock
    "facilitator-sees-signed-tx",      # no TEE-resident verifier exists yet
    "merchant-knows-price",            # the resource server set the amount
)
REQUIRED_DISCLOSURE = {
    "ephemeral-to-ephemeral": _COMMON_DISCLOSURE + ("eata-commit-reveals-balance",),
    "base-to-stealth": _COMMON_DISCLOSURE + (
        "sender-public-on-base",       # shuttle deposit is a base-chain tx
        "deposit-amount-public",       # instruction 25 carries the u64 in clear
        "delivery-splits-public",      # queued vault -> ATA deliveries on Solana
    ),
}


class PrivateErError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _fail(reason):
    raise PrivateErError(reason)


def _pubkey(value, reason):
    if not isinstance(value, str) or not 32 <= len(value) <= 44:
        _fail(reason)
    try:
        key = Pubkey.from_string(value)
    except (ValueError, TypeError):
        _fail(reason)
    if str(key) != value:
        _fail(reason)
    return key


def _amount(value, reason="invalid_amount", allow_zero=False):
    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]{0,19}", value):
        _fail(reason)
    number = int(value)
    if number > U64_MAX or (number == 0 and not allow_zero):
        _fail(reason)
    return number


def _network(network):
    if network == MAINNET:
        _fail("mainnet_disabled")
    if network != DEVNET:
        _fail("unsupported_network")


def _strict(obj, keys, reason, optional=frozenset()):
    if not isinstance(obj, dict) or not set(keys) - set(optional) <= set(obj) or not set(obj) <= set(keys):
        _fail(reason)


def canonical_json(value):
    """RFC 8785-style canonical JSON for comparison (matches protocols.ts)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def is_advertised(supported, scheme, network=DEVNET, x402_version=2):
    """True only if ``/supported`` lists the exact (version, scheme, network)."""
    kinds = (supported or {}).get("kinds")
    return isinstance(kinds, list) and any(
        isinstance(k, dict) and k.get("x402Version") == x402_version and k.get("scheme") == scheme
        and k.get("network") == network for k in kinds)


# ── exact-magicblock (MagicBlock reference scheme) ─────────────────────────

def validate_exact_magicblock(req):
    """Shape-check a MagicBlock ``exact-magicblock`` accepted requirement.

    Mirrors ``createX402PaymentRequired`` in protocols.ts. Devnet clusters only.
    This does not verify the prepared transaction or any signature.
    """
    _strict(req, REQUIREMENT_KEYS, "invalid_requirements")
    if req["scheme"] != EXACT_MAGICBLOCK:
        _fail("wrong_scheme")
    extra = req["extra"]
    if not isinstance(extra, dict):
        _fail("invalid_requirements")
    cluster = extra.get("cluster")
    if cluster in MAINNET_CLUSTERS:
        _fail("mainnet_disabled")
    _network(req["network"])
    if cluster not in MAGICBLOCK_CLUSTERS:
        _fail("unsupported_cluster")
    _amount(req["amount"])
    if req["asset"] != DEVNET_USDC:
        _fail("unsupported_asset")
    _pubkey(req["payTo"], "invalid_pay_to")
    for field in ("payer", "validator"):
        _pubkey(extra.get(field), "invalid_" + field)
    if extra.get("settlement") != "ephemeral-rollup" or extra.get("assetTransferMethod") != "delegated-spl":
        _fail("invalid_settlement")
    if not isinstance(extra.get("paymentId"), str) or not 0 < len(extra["paymentId"]) <= 128:
        _fail("invalid_payment_id")
    if type(req["maxTimeoutSeconds"]) is not int or req["maxTimeoutSeconds"] <= 0:
        _fail("invalid_timeout")
    return {"cluster": cluster, "amount": int(req["amount"]), "payTo": req["payTo"], "payer": extra["payer"]}


# ── musebook-sealed-er (experimental, toward Dark x402 properties) ─────────

def stealth_pool_pda(handle):
    """Derive the ephemeral-spl-token stealth-pool PDA for an exact UTF-8 handle.

    Seeds follow ``e-token-api/src/state/stealth_pool.rs``: ``stealth_pool`` +
    handle (<=32 bytes); + handle[:32], handle[32:] (<=64); or + handle[:32],
    sha256(``stealth_pool_handle`` || handle) (<=255). Handles are not normalized.
    """
    if not isinstance(handle, str):
        _fail("invalid_handle")
    raw = handle.encode("utf-8")
    if not 0 < len(raw) <= 255:
        _fail("invalid_handle")
    seeds = [b"stealth_pool"]
    if len(raw) <= 32:
        seeds.append(raw)
    elif len(raw) <= 64:
        seeds += [raw[:32], raw[32:]]
    else:
        seeds += [raw[:32], hashlib.sha256(b"stealth_pool_handle" + raw).digest()]
    return str(Pubkey.find_program_address(seeds, Pubkey.from_string(EPHEMERAL_SPL_PROGRAM))[0])


def resource_commitment(resource_url, nonce_hex):
    """Endpoint binding that never travels on-chain or to the facilitator in clear."""
    if not isinstance(resource_url, str) or not resource_url or not re.fullmatch(r"[0-9a-f]{64}", str(nonce_hex)):
        _fail("invalid_commitment_input")
    return hashlib.sha256(COMMITMENT_DOMAIN + b"\0" + resource_url.encode("utf-8") + b"\0"
                          + bytes.fromhex(nonce_hex)).hexdigest()


def validate_sealed_requirements(req):
    """Validate a ``musebook-sealed-er`` v0 accepted requirement. Returns a summary."""
    _strict(req, REQUIREMENT_KEYS, "invalid_requirements")
    if req["scheme"] != SEALED_SCHEME:
        _fail("wrong_scheme")
    extra = req["extra"]
    _strict(extra, SEALED_EXTRA_KEYS, "invalid_extra", SEALED_EXTRA_OPTIONAL)
    if extra["cluster"] in MAINNET_CLUSTERS:
        _fail("mainnet_disabled")
    _network(req["network"])
    if extra["cluster"] != "devnet-private":
        _fail("private_cluster_required")  # public ER executes but does not keep payments private
    if extra["programId"] != EPHEMERAL_SPL_PROGRAM:
        _fail("invalid_program")
    _pubkey(extra["validator"], "invalid_validator")
    amount = _amount(req["amount"])
    if req["asset"] != DEVNET_USDC:
        _fail("unsupported_asset")
    route = extra["route"]
    if route not in SEALED_ROUTES:
        _fail("unsupported_route")
    if route == "base-to-stealth":
        if "recipient" in extra or "recipientHandle" not in extra:
            _fail("stealth_handle_required")
        if req["payTo"] != stealth_pool_pda(extra["recipientHandle"]):
            _fail("pay_to_not_stealth_pool")
    else:
        if "recipientHandle" in extra or "recipient" not in extra:
            _fail("recipient_required")  # API: stealth handles only exist on base -> base
        _pubkey(extra["recipient"], "invalid_recipient")
        if req["payTo"] != extra["recipient"]:
            _fail("pay_to_mismatch")
    min_delay = _amount(extra["minDelayMs"], "invalid_delay", allow_zero=True)
    max_delay = _amount(extra["maxDelayMs"], "invalid_delay", allow_zero=True)
    if max_delay < min_delay or max_delay > MAX_DELAY_MS:
        _fail("invalid_delay")
    split = extra["split"]
    if type(split) is not int or not 1 <= split <= MAX_SPLIT or split > amount:
        _fail("invalid_split")
    if not isinstance(extra["resourceCommitment"], str) or not re.fullmatch(r"[0-9a-f]{64}", extra["resourceCommitment"]):
        _fail("invalid_resource_commitment")
    if extra["receipt"] != "settlement-only":
        _fail("invalid_receipt_mode")
    if extra["disclosure"] != list(REQUIRED_DISCLOSURE[route]):
        _fail("disclosure_mismatch")
    if type(req["maxTimeoutSeconds"]) is not int or not 0 < req["maxTimeoutSeconds"] <= 600:
        _fail("invalid_timeout")
    return {"route": route, "amount": amount, "payTo": req["payTo"], "split": split}


def _decode_tx(value):
    if not isinstance(value, str) or not 0 < len(value) <= MAX_TX_BASE64 or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", value):
        _fail("invalid_transaction")
    try:
        raw = base64.b64decode(value, validate=True)
        tx = VersionedTransaction.from_bytes(raw)
    except (binascii.Error, ValueError):
        _fail("invalid_transaction")
    if base64.b64encode(bytes(tx)).decode() != value:
        _fail("non_canonical_transaction")
    return tx


def check_sealed_transaction(tx_b64):
    """Leak screen for the owner-signed transaction. Not a facilitator verifier.

    Rejects memo instructions (an on-chain ``payment:<id>`` or URL defeats endpoint
    sealing) and direct SPL Token / Token-2022 instructions (the ordinary
    ``exact-magicblock`` transfer shape). Requires the ephemeral-spl-token program.
    The instruction data itself is NOT decoded or checked here.
    """
    tx = _decode_tx(tx_b64)
    message = tx.message
    keys = [str(k) for k in message.account_keys]
    programs = {keys[ix.program_id_index] for ix in message.instructions if ix.program_id_index < len(keys)}
    if len(programs) != len({ix.program_id_index for ix in message.instructions}):
        _fail("invalid_transaction")
    if programs & MEMO_PROGRAMS:
        _fail("memo_leak")
    if programs & TOKEN_PROGRAMS:
        _fail("plain_token_transfer")
    if EPHEMERAL_SPL_PROGRAM not in programs:
        _fail("missing_ephemeral_spl_instruction")
    if message.header.num_required_signatures < 1 or not all(tx.verify_with_results()):
        _fail("unsigned_transaction")  # every required signer, incl. the owner, must have signed
    return {"feePayer": keys[0], "programs": sorted(programs)}


def validate_sealed_payload(payload, requirements):
    """Validate a ``musebook-sealed-er`` x402 v2 PaymentPayload against the accepted requirement.

    The payload deliberately omits x402's ``resource`` object: the endpoint is
    carried only as ``resourceCommitment``. Agent/messaging key material is refused.
    """
    _strict(payload, {"x402Version", "accepted", "payload"}, "invalid_payload")
    if payload["x402Version"] != 2:
        _fail("unsupported_version")
    validate_sealed_requirements(requirements)
    if canonical_json(payload["accepted"]) != canonical_json(requirements):
        _fail("requirements_mismatch")
    inner = payload["payload"]
    if isinstance(inner, dict) and set(inner) & {"agentKey", "jwk", "privateKey", "secretKey", "grant", "agentAuth"}:
        _fail("agent_key_material")
    _strict(inner, {"transaction", "resourceCommitment"}, "invalid_payload")
    if not hmac.compare_digest(str(inner["resourceCommitment"]), requirements["extra"]["resourceCommitment"]):
        _fail("resource_commitment_mismatch")
    return check_sealed_transaction(inner["transaction"])


def verify_resource_binding(requirements, resource_url, nonce_hex):
    """Resource server side: the commitment it issued must open to its own URL."""
    expected = resource_commitment(resource_url, nonce_hex)
    if not hmac.compare_digest(expected, requirements["extra"]["resourceCommitment"]):
        _fail("resource_commitment_mismatch")
    return True


def sealed_settlement_response(signature, requirements, success=True, pending=False):
    """Settlement-only response: no payer, no amount, no resource URL."""
    if not isinstance(signature, str) or not 64 <= len(signature) <= 88:
        _fail("invalid_signature")
    body = {"success": bool(success) and not pending, "transaction": signature, "network": requirements["network"],
            "extensions": {SEALED_SCHEME: {"settlement": "ephemeral-rollup",
                                           "resourceCommitment": requirements["extra"]["resourceCommitment"]}}}
    if pending:
        body["errorReason"] = "settlement_pending"
    return body


def assert_settlement_only(response):
    """Reject a settlement response that leaks the fields sealing is meant to hide."""
    if not isinstance(response, dict):
        _fail("invalid_settlement_response")
    leaked = {"payer", "amount", "resource", "payTo"} & set(response)
    ext = (response.get("extensions") or {}).get(SEALED_SCHEME) or {}
    leaked |= {"payer", "amount", "resource", "payTo"} & set(ext)
    if leaked:
        _fail("settlement_leak:" + ",".join(sorted(leaked)))
    return True


def privacy_profile(req):
    """Who can see what, for either profile. Values are claims about design, not audits."""
    scheme = (req or {}).get("scheme")
    if scheme == EXACT_MAGICBLOCK:
        cluster = validate_exact_magicblock(req)["cluster"]
        private = cluster == "devnet-private"
        return {
            "scheme": scheme, "cluster": cluster,
            "publicObserversSee": (["base-chain delegation records"] if private
                                   else ["payer", "recipient", "amount", "memo payment:<id>"]),
            "paymentServiceSees": ["payer", "recipient", "amount", "memo payment:<id>"],
            "settlementResponseIncludes": ["payer", "amount", "transaction"],
            "darkX402": {"payerSealed": False, "amountSealed": False, "endpointSealed": False, "settlementOnly": False},
        }
    if scheme == SEALED_SCHEME:
        route = validate_sealed_requirements(req)["route"]
        base = route == "base-to-stealth"
        return {
            "scheme": scheme, "cluster": "devnet-private", "route": route,
            "publicObserversSee": (["sender", "deposit amount", "delayed delivery splits"] if base
                                   else ["eATA state only when committed to Solana"]),
            "paymentServiceSees": ["signed transaction (payer, amount)"],
            "settlementResponseIncludes": ["transaction", "resourceCommitment"],
            "disclosure": list(REQUIRED_DISCLOSURE[route]),
            "darkX402": {"payerSealed": not base, "amountSealed": not base, "endpointSealed": True,
                         "settlementOnly": True, "facilitatorBlind": False},
        }
    _fail("wrong_scheme")
