# ClawBro

A lightweight personal AI assistant that runs in your terminal. It routes each
message to the best-matching **skill**, falls back to a general Claude assistant
when nothing specific fits, and remembers your conversation in a local SQLite
database. Built to run comfortably on anything from a Raspberry Pi to a laptop —
single process, no daemon, under ~100 MB RAM at idle.

Claude is the default brain. A local or cloud [Ollama](https://ollama.com) model
can serve as an offline fallback.

---

## Quickstart

```bash
# 1. Clone and enter the project
git clone https://github.com/apgit67/clawbro.git
cd clawbro

# 2. Create a virtual environment and install dependencies
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Add your API key
cp .env.example .env                 # Windows: copy .env.example .env
#   then edit .env and set ANTHROPIC_API_KEY=sk-ant-...

# 4. Run
python src/main.py
```

On first run, ClawBro pings the Claude API, creates its SQLite database at
`~/.clawbro/memory.db`, and drops you into an interactive prompt. Type a message,
or `/help` for commands.

For full installation details — Ollama, the Telegram/Discord bots, optional file
formats, and troubleshooting — see **[SETUP.md](SETUP.md)**.

---

## Requirements

- **Python 3.11+**
- An **Anthropic API key** ([console.anthropic.com](https://console.anthropic.com)) —
  unless you run entirely in Ollama offline mode.

---

## Usage

```bash
python src/main.py [options]
```

| Option | Description |
|--------|-------------|
| `--model MODEL` | Override the Claude model (default: `CLAUDE_MODEL` env or `claude-sonnet-4-6`) |
| `--ollama` | Use a local/cloud Ollama model instead of the Claude API |
| `--ollama-model NAME` | Ollama model name (default: `OLLAMA_MODEL` env or `llama3`) |
| `--db PATH` | SQLite database path (default: `~/.clawbro/memory.db`) |
| `--no-health-check` | Skip the Claude API ping on startup for a faster cold start |

### Slash commands (inside the prompt)

| Command | Description |
|---------|-------------|
| `/help` | Show available skills and commands |
| `/memory` | List all long-term memory keys |
| `/remember <text>` | Save a fact to long-term memory |
| `/clear` | Clear the current session's conversation history |
| `/status` | Health check: database, Claude API, Ollama |
| `/quit` or `/exit` | Exit ClawBro |

---

## Skills

ClawBro scores every skill against your message and dispatches to the highest
match (confidence threshold 0.4). If nothing clears the bar, the general-purpose
**fallback** assistant handles it.

| Skill | What it does |
|-------|--------------|
| **system_architect** | System design diagrams and architecture documents |
| **knowledge_synthesizer** | Links and synthesizes ideas across sources |
| **technical_proposal_generator** | Drafts RFCs and technical specifications |
| **data_repurposer** | Converts and restructures data between formats |
| **sandbox_guard** | Code-safety analysis and sandboxing advice |
| **system_pulse** | Local system health: CPU, RAM, disk (via `psutil`) |
| **research_summarizer** | Summarizes articles and papers |
| **file_writer** | Generates content and writes it to a file: `.txt`, `.md`, `.csv`, `.json`, `.html`, `.docx`, `.pdf` |
| **fallback** | General Claude assistant when no skill matches |

`file_writer` saves to `~/.clawbro/files/` by default. For safety, requested
paths are contained to that directory — only the filename of any explicit path
is honored. The `.docx` and `.pdf` formats require the optional `python-docx`
and `fpdf2` packages.

---

## Configuration

All configuration is read from a `.env` file in the project root (see
[`.env.example`](.env.example)). Key variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes* | — | Your Anthropic API key (*not needed in Ollama-only mode) |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-6` | Default Claude model |
| `CLAUDE_MAX_TOKENS` | No | `2048` | Max tokens per response |
| `CLAWBRO_DB_PATH` | No | `~/.clawbro/memory.db` | SQLite database path |
| `CLAWBRO_LOG_PATH` | No | `~/.clawbro/clawbro.log` | Log file path |
| `TELEGRAM_BOT_TOKEN` | No | — | Enables the Telegram adapter |
| `TELEGRAM_ALLOWED_USER_IDS` | No | — | Comma-separated allowlist of Telegram user IDs |
| `DISCORD_BOT_TOKEN` | No | — | Enables the Discord adapter |
| `OLLAMA_ENABLED` | No | `false` | Route to Ollama instead of Claude |
| `OLLAMA_MODEL` | No | `llama3` | Ollama model name |
| `OLLAMA_HOST` | No | `http://localhost:11434` | Ollama endpoint |
| `OLLAMA_API_KEY` | No | — | Required for cloud-hosted Ollama models |

> **Security:** the Telegram bot **fails closed** — if
> `TELEGRAM_ALLOWED_USER_IDS` is unset or empty, every message is rejected. Set
> it to your own user ID before exposing the bot. Never commit your `.env`; it
> is already in `.gitignore`.

---

## Architecture

```
Adapter (CLI / Telegram / Discord)
   → SkillRouter        scores skills, dispatches the best match
     → Skill.handle()   builds a prompt, calls Claude, returns a result
       → ClaudeClient   streams from the Anthropic API (or Ollama fallback)
     → MemoryStore      SQLite short-term history + FTS5 long-term facts
```

The full design — module boundaries, data flow, and API contracts — lives in
[`architecture/architecture.md`](architecture/architecture.md).

---

## Testing

```bash
pytest
```

---

## License

Personal project. No license specified.
