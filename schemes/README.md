# Musebook Solana schemes

Adapted from the scheme-directory structure in `a2a-x402-main` (vendored from https://github.com/Solizardking/a2a-x402; see `../a2a-x402-main/PROVENANCE.md`).
Start at https://musebook.trade/x402.

| Profile | Contract | Local status |
| --- | --- | --- |
| [SVM batch-settlement](scheme_batch_settlement_svm.md) | One escrow channel; many cumulative vouchers; later claim and distribute | Primary focus: full supplied spec plus Python cryptography/accounting; no hosted rail |
| [Solana exact](scheme_exact_solana.md) | One exact SPL transfer using the selected upstream x402 version | Reference integration boundary |
| [Private ER: `exact-magicblock` reference](scheme_private_er_solana.md#exact-magicblock-magicblock-reference-scheme) | MagicBlock checkout: one delegated-USDC transfer on an Ephemeral Rollup, ER settlement | Upstream scheme; shape checks only; not advertised by musebook.trade |
| [Private ER: `musebook-sealed-er` v0](scheme_private_er_solana.md#musebook-sealed-er-v0-experimental) | Owner-signed private ER transfer; endpoint by commitment; settlement-only response | Experimental, devnet-private only, toward Dark x402 properties; not live |
| [Historical x402m batch v0](scheme_x402m_batch_v0.md) | One payer, up to eight USDC transfers in a transaction | Existing experimental reference |

`batch-settlement`, `upto`, eight-transfer batch v0 and the private ER profiles are
separate contracts. `musebook-sealed-er` is our composition, not Dark x402 and not a
MagicBlock product.
Consult [live advertisement observations](../docs/batch-settlement-status.json)
and require an actual matching `/api/x402/supported` entry before live selection.
The snapshot is dated; it is not a deployment promise.
