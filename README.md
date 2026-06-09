# QA Automation Agent

AI-powered browser automation platform using local LLMs.

---

## System Requirements

### 1. Python
- **Version:** 3.10 or higher
- **Download:** https://www.python.org/downloads/
- **Note:** Check "Add Python to PATH" during install

### 2. Node.js
- **Version:** 18 or higher
- **Download:** https://nodejs.org/en/download
- **Includes:** npm (no separate install needed)

### 3. Ollama
- **Version:** Latest
- **Download:** https://ollama.com/download/windows
- **Note:** Install and run once before starting the app

### 4. Ollama Models
Pull these after installing Ollama:

```bash
ollama pull qwen2.5:0.5b      # LLM Model    (~400 MB)
ollama pull moondream:latest   # Vision Model (~1.7 GB)
```

### 5. Playwright Chromium
Auto-installed by backend setup, or run manually:

```bash
python -m playwright install chromium
```

---

## Installation

### Backend
```bash
cd backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\playwright install chromium
```

### Frontend
```bash
cd frontend
npm install
```

---

## How to Start

**1. Start Backend**
```bash
cd backend
venv\Scripts\uvicorn app.main:app --reload --port 8000
```

**2. Start Frontend**
```bash
cd frontend
npm run dev
```

**3. Open Browser**
```
http://localhost:3000
```

**Login:** `admin` / `admin123`

---

## Python Packages (auto-installed via requirements.txt)

| Package | Version |
|---------|---------|
| fastapi | 0.115.6 |
| uvicorn[standard] | 0.32.1 |
| playwright | 1.49.1 |
| httpx | 0.28.1 |
| pydantic | 2.10.4 |
| python-jose[cryptography] | 3.3.0 |
| passlib[bcrypt] | 1.7.4 |
| python-multipart | 0.0.20 |
| python-dotenv | 1.0.1 |
| aiofiles | 24.1.0 |
| reportlab | >=4.2.0 |
| pytest | 8.3.4 |
| pytest-asyncio | 0.25.0 |

## NPM Packages (auto-installed via npm install)

| Package | Version |
|---------|---------|
| next | 15.1.3 |
| react | ^19.0.0 |
| axios | ^1.7.9 |
| tailwindcss | ^3.4.17 |
| typescript | ^5.7.3 |
| lucide-react | ^0.469.0 |
| @radix-ui/react-* | ^1.x |
