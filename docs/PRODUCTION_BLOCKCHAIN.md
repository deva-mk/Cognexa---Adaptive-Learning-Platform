# Moving the audit ledger from local Hardhat to a public network

**Status: not deployed.** Deploying needs a funded wallet and an RPC provider account that only you can create.
Everything that can be tested without them is tested (signed-key path, chain-id guard, confirmations,
production config rules - see `backend/tests/test_10_*`).

Use a **testnet (Sepolia) first**. Never reuse a Hardhat key, and never put a key in git, a screenshot or a chat.

1. Create a **new** wallet only for this project. Fund it with Sepolia test ETH from a faucet.
2. Get an RPC URL (Alchemy, Infura, or your own node).
3. In PowerShell (keys live only in this shell session):
   ```powershell
   $env:SEPOLIA_RPC_URL = "https://eth-sepolia.g.alchemy.com/v2/<key>"
   $env:DEPLOYER_PRIVATE_KEY = "<64 hex chars, no 0x needed>"
   ```
4. Deploy with the backend CLI (the deployer becomes the contract's only *registrar*):
   ```powershell
   cd backend
   python -m app.cli deploy-contract      # uses BLOCKCHAIN_RPC_URL / BLOCKCHAIN_PRIVATE_KEY from .env
   ```
5. In `.env` set: `BLOCKCHAIN_RPC_URL`, `CONTRACT_ADDRESS` (printed by step 4), `BLOCKCHAIN_PRIVATE_KEY`
   (the same registrar key), `BLOCKCHAIN_EXPECTED_CHAIN_ID=11155111`, `BLOCKCHAIN_CONFIRMATIONS=2`, `ENVIRONMENT=production`.
   Startup refuses to run in production if the chain id or key is missing, the key is a public Hardhat key, or the RPC is localhost.
6. Open **Ledger -> chain status**: it must show connected, code present, interface OK and `bytecode_matches_artifact: true`.
7. Complete one assessment as a student, then press **Verify**; expect `VERIFIED`. Check the transaction on a block explorer.

Privacy: only keyed hashes and opaque record references go on-chain - never names, scores or e-mail. Public chains are permanent
and cannot be erased; keep that in mind before mainnet. Keep the registrar key in a secrets manager and rotate it by deploying a new contract.
