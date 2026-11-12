# Musebook private ER profiles (experimental, devnet only)

Private x402 payments on Solana through MagicBlock Ephemeral Rollups (ERs),
using the ephemeral SPL token program. This page covers two schemes:

| Scheme | Owner | Status |
| --- | --- | --- |
| `exact-magicblock` | MagicBlock, upstream reference | Defined upstream, not advertised by `musebook.trade` |
| `musebook-sealed-er` v0 | Musebook, experimental | Wire checks only. Not advertised, not settled, not live. |

`musebook-sealed-er` works toward the **Dark x402** goal described by
[Dark Percolator](https://dark.percolator.tech): "HTTP 402 payments for agents,
where the payer, the amount and the endpoint stay sealed and only settlement
comes back out." Dark Percolator lists Dark x402 as a roadmap concept that is
not built. This profile **is not Dark x402** and **is not a MagicBlock
product**. It is our own composition of public MagicBlock components, in the same
spirit as the Dark Percolator explainer ("our composition, not a MagicBlock
product").

Upstream reference: https://github.com/magicblock-labs/ephemeral-spl-token
(read at `41476b7`). See its `README.md`, `e-token/README.md`, `api/PAYMENTS.md`,
`api/README.md` and `api/src/payments/protocols.ts`. Nothing from that tree is
vendored here.

Network: `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1` (devnet), with the MagicBlock
cluster `devnet-private` (the TEE ER, `EPHEMERAL_DEVNET_TEE_RPC_URL`). Asset: devnet
USDC `4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU`, 6 decimals. **Mainnet and
`mainnet-private` are rejected** by every helper in this repo.

## Building blocks (upstream facts)

- **Program.** Ephemeral SPL Token, `SPLxh1LVZzEkX99H6rqYizhytLWPZVV296zyYDPagv2`.
  It has a per-mint global vault and owner/mint ephemeral ATAs (eATAs). eATAs are
  program state, not SPL token accounts. Delegation moves them into the ER, and
  committing writes their state back to Solana.
- **Private transfers.** Recipient and timing parameters are encrypted. Funds are
  staged through a temporary shuttle, the payment is queued inside the rollup,
  and it settles later on Solana from the per-mint vault. Instruction 25
  (`DepositAndDelegateShuttleEphemeralAtaWithMergeAndPrivateTransfer`) **does not
  itself pay the recipient**. Shuttle cleanup and recipient delivery are separate
  completion points. Its instruction data carries the deposit amount as a
  plaintext `u64`. Delays (`minDelayMs`/`maxDelayMs`, max 2,678,400,000 ms) and
  `split` (1–15) blur timing and size.
- **Stealth pools.** A payment can be addressed to a handle. The pool PDA is
  derived from the exact UTF-8 handle with no normalization, and it holds 1–10
  destination keys. The API only accepts stealth handles for private
  `base -> base` transfers.
- **Private ER visibility.** The `-private` clusters run on a TEE-backed
  (Intel TDX) ER operated by MagicBlock. Account permissions decide what is
  readable. Choosing a private cluster string does not onboard any accounts.

## `exact-magicblock` (MagicBlock reference scheme)

This is MagicBlock's x402 v2 checkout scheme. The matching MPP method is
`magicblock` with intent `charge`. It pays with already-delegated USDC on an ER.
`GET /v1/x402/supported` on a configured MagicBlock payments service advertises
it for the configured clusters, including `devnet-private`.

- A checkout is **one ordinary SPL transfer** between projected ATAs, plus a
  `payment:<paymentId>` memo. Both eATAs must already be delegated to the same
  validator.
- The fee is exactly zero. The buyer is the fee payer and signs. There is no
  sponsorship, relay fee, account creation, deposit or withdrawal.
- `accepts[0]` contains `scheme`, `network`, `amount`, `asset`, `payTo`,
  `maxTimeoutSeconds: 60` and `extra`. The `extra` object holds `paymentId`,
  `merchantId`, `payer`, `cluster`, `validator`, `settlement: "ephemeral-rollup"`,
  `resource`, the prepared `transaction`, `recentBlockhash`, `lastValidBlockHeight`,
  `expiresAt`, `assetTransferMethod: "delegated-spl"` and `paymentFlow: "upfront"`.
- `paid` means **ER settlement**, not L1 commitment or withdrawal. Verification
  never establishes payment.
- **Privacy gap (stated upstream).** "The service still sees the sender, recipient
  and amount in the transaction it processes." The x402 settlement response
  echoes `payer` and `amount`. Today's privacy comes mostly from TEE-backed
  private ER visibility. Queued private transfers add hidden destination and
  timing on the public base chain. That is **not** Dark x402.

`x402m.core.private_er.validate_exact_magicblock` shape-checks an accepted
requirement on devnet clusters. It does not verify the prepared transaction.
Use MagicBlock's own client (`createPaymentCredential`) to build and sign.

## `musebook-sealed-er` v0 (experimental)

Target properties are measured against public observers and the settlement output:

| Property | `ephemeral-to-ephemeral` | `base-to-stealth` |
| --- | --- | --- |
| Payer sealed | Yes (inside the TEE) | **No**: the shuttle deposit is a base-chain tx |
| Amount sealed | Yes (inside the TEE) | **No**: instruction 25 carries the deposit amount in clear, and delivery splits are public |
| Endpoint sealed | Yes: only `resourceCommitment` | Yes: only `resourceCommitment` |
| Settlement-only output | Yes | Yes |
| Facilitator blind | **No** (not built) | **No** (not built) |

The TEE validator still sees everything, and so does any facilitator that
verifies the signed transaction outside a TEE. Privacy rests on Intel TDX operated
by MagicBlock.

### PaymentRequirements

```json
{
  "scheme": "musebook-sealed-er",
  "network": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
  "amount": "1000",
  "asset": "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
  "payTo": "<recipient wallet, or the stealth-pool PDA for base-to-stealth>",
  "maxTimeoutSeconds": 60,
  "extra": {
    "cluster": "devnet-private",
    "programId": "SPLxh1LVZzEkX99H6rqYizhytLWPZVV296zyYDPagv2",
    "validator": "<TEE validator pubkey>",
    "route": "ephemeral-to-ephemeral",
    "recipient": "<pubkey>",
    "minDelayMs": "0",
    "maxDelayMs": "30000",
    "split": 3,
    "resourceCommitment": "<64 hex>",
    "receipt": "settlement-only",
    "disclosure": ["tee-validator-sees-payment", "facilitator-sees-signed-tx",
                   "merchant-knows-price", "eata-commit-reveals-balance"]
  }
}
```

Rules, enforced by `validate_sealed_requirements`:

- `cluster` must be `devnet-private`. The public `devnet` ER executes payments but
  does not keep them private. `programId` must be the ephemeral SPL program.
- `route` is `ephemeral-to-ephemeral`, which requires `recipient` and
  `payTo == recipient`, or `base-to-stealth`, which requires `recipientHandle` and
  `payTo == stealth_pool_pda(recipientHandle)`. Extra keys are strict, so there is
  no `memo`, `resource` URL or `paymentId` on the wire.
- `disclosure` must equal the exact list for the route
  (`REQUIRED_DISCLOSURE`). Neither side can claim more privacy than the route
  provides. The `base-to-stealth` list adds `sender-public-on-base`,
  `deposit-amount-public` and `delivery-splits-public`.
- `resourceCommitment = sha256("musebook-sealed-er/v0/resource" || 0x00 || url || 0x00 || nonce32)`.
  The resource server keeps `url` and `nonce` and re-opens the commitment with
  `verify_resource_binding`.

### PaymentPayload

```json
{ "x402Version": 2, "accepted": { "...": "byte-identical requirements" },
  "payload": { "transaction": "<owner-signed base64 tx>", "resourceCommitment": "<64 hex>" } }
```

There is no x402 `resource` object, so the endpoint never reaches the
facilitator in clear. Agent or messaging key fields (`agentKey`, `jwk`,
`privateKey`, `grant`, …) are rejected. `check_sealed_transaction` verifies every
required signature. It rejects memo programs (an on-chain `payment:<id>` or URL
would defeat sealing) and direct SPL Token or Token-2022 instructions (the
`exact-magicblock` transfer shape), and it requires an ephemeral SPL
instruction. It is a **leak screen, not a verifier**: it does not decode or
check instruction data.

### Settlement response

`sealed_settlement_response` returns only `success`, `transaction` (the ER
signature), `network`, and `extensions["musebook-sealed-er"] = {settlement:
"ephemeral-rollup", resourceCommitment}`. `assert_settlement_only` rejects any
response carrying `payer`, `amount`, `payTo` or `resource`. A pending result is
`success: false` with `errorReason: "settlement_pending"`. Verification is not
settlement, and ER settlement is not L1 commitment.

## Authority

The wallet owner reviews the mint, network, recipient or handle, amount, split,
delays and disclosure list, and signs. x402m agent keys authenticate mailbox
messages only. They never sign, fund or spend. `payment.request` and
`payment.receipt` messages may carry these requirements or a settlement
signature, but they authorize nothing. No automatic spending is enabled.

## Live status

A read-only `GET https://musebook.trade/api/x402/supported` on 2026-11-12 at
13:34 UTC returned only `exact` kinds (Solana mainnet and devnet in v1 and v2,
plus EVM Gateway rails), with `extensions: []`. Neither `exact-magicblock` nor
`musebook-sealed-er` is advertised. A client MUST NOT select either scheme unless
the facilitator's `/supported` lists the exact `(x402Version, scheme, network)`.
`is_advertised` implements that check.

## Remaining gaps before advertising `musebook-sealed-er`

1. **A TEE-resident verifier and facilitator.** Without one, the facilitator sees
   the signed transaction, so `facilitatorBlind` stays false. The design target
   is verification inside the private ER/TDX, with only the signature and
   commitment exiting.
2. **Instruction-level verification.** Someone needs to decode the ephemeral SPL
   private-transfer instructions (destination, mint, amount, split, delays) and
   check them against the requirements. That needs either the recipient's view
   inside the private ER or a TEE attestation.
3. **Settlement confirmation.** The facilitator must poll `getSignatureStatuses`
   on the private ER with its own service identity, and replay-protect the
   signature. For `base-to-stealth`, delivery is queued and happens later.
4. **Leak control after settlement.** eATA commits publish balance state on
   Solana, so commit cadence and batching across payers are needed before the
   amount stays sealed over time.
5. **Upstream onboarding.** The queue for the mint and validator must exist and
   be delegated, permissions must be set, and stealth pools must be initialized.
   None of this was run for this document. No devnet or mainnet transactions were
   sent.
6. **Review.** This is unaudited and experimental. It needs independent review
   before any funded use.

## Related alternative: Token-2022 confidential transfers

The vendored pay-kit (`pay-kit-main/rust/crates/kit`,
`docs/confidential-transfers.md`) implements MPP charges settled as Token-2022
confidential transfers. They hide the amount with ElGamal and ZK proofs on the
base chain, but the payer, the recipient account and the gateway-paid bundle stay
public. They need a confidential-transfer-enabled Token-2022 mint (pay-kit's
built-in list names only a mainnet mint), and they are not an x402 scheme here. They are
a possible complement for the amount, not the headline.

## The old batch `private: true` flag

The historical batch planner's `private: true` only suppresses the public receipt
write. It **does not hide the on-chain transfer**. See [payments](../docs/payments.md).
