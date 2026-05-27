# ClawBro — Setup & Run Guide

This walks through installing and running ClawBro from a clean checkout, on both
Windows (PowerShell) and Linux/macOS. For a feature overview and the skill list,
see [README.md](README.md).

---

## 1. Prerequisites

- **Python 3.11 or newer.** Check with `python --version`.
- **An Anthropic API key.** Create one at
  [console.anthropic.com](https://console.anthropic.com). You only need this if
  you use Claude (the default). Pure Ollama offline mode does not require it.
- **Git**, to clone the repository.

---

## 2. Get the code

```bash
git clone https://github.com/apgit67/clawbro.git
cd clawbro
```

---

## 3. Create a virtual environment

A virtual environment keeps ClawBro's dependencies isolated from the rest of
your system.

**Linux / macOS:**
```bash
python -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

> If PowerShell blocks the activation script, run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try again.

Your prompt should now be prefixed with `(.venv)`.

---

## 4. Install dependencies

```bash
pip install -r requirements.txt
```

This installs the core packages plus the optional adapters and file formats. If
you want a minimal core-only install, you can comment out the optional sections
in `requirements.txt` first — see the comments in that file.

---

## 5. Configure your environment

Copy the example file and edit it:

**Linux / macOS:**
```bash
cp .env.example .env
```

**Windows (PowerShell):**
```powershell
copy .env.example .env
```

Open `.env` and set at minimum:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Everything else has sensible defaults. The full list of variables is documented
in the [Configuration table in the README](README.md#configuration).

> **Never commit `.env`.** It holds secrets and is already listed in
> `.gitignore`.

---

## 6. Run ClawBro

```bash
python src/main.py
```

On startup you'll see a banner reporting the status of the database, Claude API,
and optional adapters, followed by an interactive prompt. Type a message, or
`/help` to list skills and commands. `/quit` exits.

The SQLite database and log file are created under `~/.clawbro/` on first run.

---

## 7. Offline mode with Ollama (optional)

ClawBro can route to a local or cloud [Ollama](https://ollama.com) model instead
of the Claude API.

**Local models:**
1. Install Ollama and pull a model: `ollama pull llama3`
2. Make sure the Ollama server is running (`ollama serve`).
3. Run ClawBro with the flag:
   ```bash
   python src/main.py --ollama --ollama-model llama3
   ```
   Or set `OLLAMA_ENABLED=true` and `OLLAMA_MODEL=llama3` in `.env`.

**Cloud-hosted models** (e.g. `glm-5.1:cloud`) require an API key. Generate one
at [ollama.com/settings/keys](https://ollama.com/settings/keys) and set it in
`.env`:
```
OLLAMA_API_KEY=your-ollama-key
OLLAMA_MODEL=glm-5.1:cloud
```

If an Ollama call returns an auth error, ClawBro automatically falls back to the
Claude API (provided `ANTHROPIC_API_KEY` is set).

---

## 8. Live web search (optional)

The `web_search` skill answers questions that need current information from the
internet (news, prices, "latest", "today") using the
[Tavily](https://tavily.com) search API, and cites its sources.

1. Install the optional package: `pip install tavily-python`
2. Get a key at [tavily.com](https://tavily.com) and add it to `.env`:
   ```
   TAVILY_API_KEY=tvly-your-key-here
   ```

Without the key (or the package), the skill returns a clear message telling you
what to install or set. Questions that don't need live data are handled by
`research_summarizer` instead.

---

## 9. Chat adapters (Telegram / Discord) — optional

The Telegram and Discord adapters are selected with the `--adapter` flag:

```bash
python src/main.py --adapter telegram
python src/main.py --adapter discord
```

Each requires its bot token to be set (`TELEGRAM_BOT_TOKEN` /
`DISCORD_BOT_TOKEN`); if the token is missing, ClawBro prints an error and
exits. The default `--adapter cli` runs the interactive terminal.

When you run the Telegram bot, **set your allowlist first**:
```
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_ALLOWED_USER_IDS=11111111,22222222
```
The bot **fails closed** — with no allowlist, it rejects every message. This
prevents a public bot from being driven by strangers on your API budget.

---

## 10. Running the tests

```bash
pytest
```

All tests should pass against a working Python 3.11+ environment.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ANTHROPIC_API_KEY is not set` | Add the key to `.env`, or run with `--ollama` for offline mode. |
| `Cannot connect to Claude API` | Check the key and your network. Use `--no-health-check` to skip the startup ping. |
| PowerShell won't run `Activate.ps1` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then re-activate. |
| `ModuleNotFoundError` | Make sure the virtual environment is activated and `pip install -r requirements.txt` completed. |
| `.docx` / `.pdf` export fails | Install the optional packages: `pip install python-docx fpdf2`. |
| Web search says key/package missing | `pip install tavily-python` and set `TAVILY_API_KEY` in `.env`. |
| Ollama auth error | Verify `OLLAMA_API_KEY` for cloud models, or run `ollama signin` for local session auth. |
| Wrong Python version | ClawBro needs 3.11+. Check `python --version`; on some systems use `python3`. |
