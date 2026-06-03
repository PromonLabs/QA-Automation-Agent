# 🤖 AutoAgent — AI Browser Automation Platform

A full-stack AI browser automation platform using local LLMs (Qwen2.5:14b via Ollama).

**Black & White** minimal design. Fully local. Fully private.

---

## Architecture

```
Frontend (Next.js)          → http://localhost:3000
FastAPI Backend             → http://localhost:8000
Ollama + Qwen2.5:14b        → http://localhost:11434
Chromium (Playwright)       → Controlled by backend
```

---

## Quick Start (Local Development)

### Prerequisites

- Python 3.11+
- Node.js 20+
- [Ollama](https://ollama.ai) installed with `qwen2.5:14b` model

### 1. Pull the LLM model

```bash
ollama pull qwen2.5:14b
ollama serve
```

### 2. Backend Setup

```bash
cd backend
python -m venv venv
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# Edit .env if needed

uvicorn app.main:app --reload --port 8000
```

### 3. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 — login with `admin` / `admin123`

---

## Docker Deployment

```bash
# Build and start all services
docker-compose up --build -d

# Pull the model (first time)
docker exec autoagent-ollama ollama pull qwen2.5:14b

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

---

## Usage

### 1. Create a Flow

Navigate to **New Flow** and either:
- Write instructions in plain English
- Paste a JSON steps object

### 2. Run It

Click **Save & Run** — the AI will:
1. Send your task to Qwen2.5:14b
2. Get back a structured execution plan
3. Open a real Chromium browser
4. Execute each step intelligently
5. Capture screenshots and logs

### 3. Watch Live

The **Execution Viewer** shows:
- Real-time logs via WebSocket
- Step-by-step progress bar
- Screenshots as they're captured

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/login` | Login |
| GET | `/api/auth/me` | Current user |
| POST | `/api/flows/create` | Create flow |
| GET | `/api/flows` | List flows |
| DELETE | `/api/flows/{id}` | Delete flow |
| POST | `/api/execution` | Start execution |
| GET | `/api/execution` | List executions |
| GET | `/api/execution/{id}` | Get execution |
| POST | `/api/execution/{id}/cancel` | Cancel |
| GET | `/api/execution/logs/{id}` | Get logs |
| GET | `/api/execution/screenshots/{id}` | Get screenshots |
| WS | `/api/execution/ws/{id}` | Live stream |

Interactive docs: http://localhost:8000/docs

---

## Sample Flows

Located in `sample-flows/`:

- `google-search.json` — Simple demo to verify setup
- `telecom-topup.json` — Mobile recharge + admin verification
- `admin-verify.json` — Admin portal customer check

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `LLM_MODEL` | `qwen2.5:14b` | Model to use |
| `ADMIN_USERNAME` | `admin` | Login username |
| `ADMIN_PASSWORD` | `admin123` | Login password |
| `SECRET_KEY` | (change!) | JWT secret |
| `BROWSER_HEADLESS` | `false` | Headless browser |
| `BROWSER_SLOW_MO` | `50` | Ms between actions |

---

## Project Structure

```
QA-App/
├── frontend/                 # Next.js app (black & white theme)
│   ├── app/
│   │   ├── login/            # Auth page
│   │   ├── dashboard/        # Stats & overview
│   │   ├── flows/            # Flow list
│   │   ├── flows/new/        # Flow builder
│   │   ├── execution/        # Execution list
│   │   └── execution/[id]/   # Live viewer
│   ├── components/           # Sidebar, Header
│   ├── hooks/                # useWebSocket
│   ├── lib/                  # API client, utils
│   └── types/                # TypeScript types
│
├── backend/                  # FastAPI app
│   ├── app/
│   │   ├── main.py           # App entry point
│   │   ├── api/routes/       # Auth, Flows, Execution
│   │   ├── agents/           # LLM client, Browser agent, Orchestrator
│   │   ├── core/             # Config, Security
│   │   ├── models/           # Pydantic schemas
│   │   └── storage/          # Filesystem artifact store
│   └── artifacts/            # Stored executions & screenshots
│
├── sample-flows/             # Ready-to-use flow examples
├── docker-compose.yml
├── Dockerfile.backend
├── Dockerfile.frontend
└── README.md
```

---

## Running the Tusass TopUp Test

The `sample-flows/flow.txt` has been converted into a fully automated test.

### Option A — Playwright direct test (fastest, no LLM needed)
```bash
cd backend
# Activate venv first
python tests/test_tusass_topup.py

# Or via pytest
python -m pytest tests/test_tusass_topup.py -v -s
```

### Option B — AI Agent test (uses Qwen2.5:14b LLM)
```bash
cd backend
python tests/agent_test_tusass.py
```

### Option C — Run via the Web UI
1. Start the platform (`.\start.ps1`)
2. Go to http://localhost:3000 → **New Flow**
3. Click **"Load sample"** — pick the Tusass flow
   OR go to **Flows** — click **Run** on "Tusass Talk Time TopUp + Admin Verify"

### Configuration
Override any value via environment variable:
```bash
set PHONE_NUMBER=236619
set TOPUP_AMOUNT=100
set CARD_CVV=121
set HEADLESS=false
python tests/test_tusass_topup.py
```

### What the test does

| Step | Action |
|------|--------|
| 1 | Open https://test.tusass.lab.gl/test |
| 2 | Click **TopUp Talk** button |
| 3 | Select amount **100** |
| 4 | Enter phone **236619** (twice if confirmation field) |
| 5 | Click Continue |
| 6 | Fill card `1000 0000 0000 0008` · `11/11` · CVV `121` |
| 7 | Click Pay · dismiss save-card dialog |
| 8 | Open https://msitcos.lab.gl/ |
| 9 | Press ESC if Microsoft login appears · login `admin@telepost.gl` |
| 10 | Search customer `236619` |
| 11 | Verify balance updated |
| 12 | Verify extra data added |
| 13 | Print final summary report + screenshots |

Screenshots saved to `backend/test-screenshots/`

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 15, React 19, TailwindCSS, shadcn/ui |
| Backend | FastAPI, Python 3.11 |
| AI/LLM | Qwen2.5:14b via Ollama |
| Browser | Playwright + Chromium |
| Real-time | WebSockets |
| Storage | Filesystem (JSON + PNG) |
| Auth | JWT (python-jose) |
| Deploy | Docker Compose |
