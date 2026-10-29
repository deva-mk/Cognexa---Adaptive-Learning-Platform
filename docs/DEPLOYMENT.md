# Public deployment (Render / any Docker host)

**Status: prepared and checked locally; not deployed.** A public host, domain and your Firebase project are accounts only you can
create. Nothing below has been run on a real host, and the `Dockerfile` has not been built (no Docker daemon in the build environment).

## 1. Prerequisites you must create
* A Firebase project -> Authentication -> enable **Email/Password**. Copy the **Web API key**. Create a **service-account JSON**
  (Project settings -> Service accounts). Never commit it.
* A host with a **persistent disk** (SQLite and uploaded files live in `DATA_DIR`) - or a managed PostgreSQL via `DATABASE_URL`.
* An LLM: run Ollama on a machine the server can reach (`OLLAMA_BASE_URL`) with `ollama pull llama3.2`. Without it the app shows
  labelled extractive answers instead of AI text.

## 2. Environment variables (set in the host's dashboard, never in git)
```
ENVIRONMENT=production      AUTH_MODE=firebase        COOKIE_SECURE=true
FIREBASE_PROJECT_ID=...     FIREBASE_WEB_API_KEY=...  GOOGLE_APPLICATION_CREDENTIALS=/data/firebase-sa.json   (upload the file to the disk)
DATA_ENCRYPTION_KEY=<python -m app.cli gen-keys>      BLOCKCHAIN_HMAC_KEY=<same command>
CORS_ORIGINS=https://your-domain       TRUSTED_PROXY_COUNT=1
DATA_DIR=/data              OCR_LANGS=eng+hin+tam+kan+mal
BLOCKCHAIN_ENABLED=false    (or follow docs/PRODUCTION_BLOCKCHAIN.md and set RPC/contract/key/chain id)
OLLAMA_BASE_URL=http://<your-ollama-host>:11434
```
Startup **refuses to boot** with an insecure production configuration and tells you exactly what is wrong.

## 3. Deploy
Render: New -> Web Service -> Docker -> attach a disk at `/data` -> add the variables -> deploy. (Fly.io, Railway, a VPS with
`docker run -p 8000:8000 -v appdata:/data --env-file prod.env <image>` behind HTTPS also work.) Run **one** backend worker: the rate limiter is in-process.

## 4. First admin (once, from the host's shell)
```
python -m app.cli create-admin --email you@school.edu --name "Your Name"
```
Then open `/` -> **Forgot password** to set the password through the Firebase e-mailed link. Create everyone else from **Admin -> Users**.

## 5. Test the public URL
```
python scripts/check_deployment.py https://your-domain --email you@school.edu --password '...'
```
Expected: every line PASS, `auth_mode=firebase environment=production`. Then sign in once as each role (student, faculty, advisor,
management, admin) and open its pages. The five-role Firebase flow is already proven on the Auth emulator
(`scripts/e2e_firebase_emulator.py`, 61/61); this step proves *your* project and host.
