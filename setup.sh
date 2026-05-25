#!/usr/bin/env bash
# setup.sh — ClawBro one-shot setup script
# Run from the outputs/ directory: bash setup.sh
set -euo pipefail

CLAWBRO_DIR="$HOME/.clawbro"
VENV_DIR=".venv"
DB_PATH="$CLAWBRO_DIR/memory.db"
REQUIRED_PYTHON_MINOR=11

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { echo "  ✓ $*"; }
warn()  { echo "  ! $*" >&2; }
fatal() { echo "  ✗ $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Check Python 3.11+
# ---------------------------------------------------------------------------
echo ""
echo "ClawBro Setup"
echo "============="
echo ""
echo "→ Checking Python version..."

PYTHON=""
for candidate in python3.11 python3.12 python3.13 python3 python; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "0")
        major=$("$candidate" -c "import sys; print(sys.version_info.major)" 2>/dev/null || echo "0")
        if [ "$major" -eq 3 ] && [ "$version" -ge "$REQUIRED_PYTHON_MINOR" ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fatal "Python 3.${REQUIRED_PYTHON_MINOR}+ is required but not found. Install it from https://python.org"
fi

PYTHON_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
info "Python $PYTHON_VERSION found at $(command -v "$PYTHON")"

# ---------------------------------------------------------------------------
# 2. Create venv at .venv/ if not exists
# ---------------------------------------------------------------------------
echo ""
echo "→ Setting up virtual environment..."

if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON" -m venv "$VENV_DIR"
    info "Created virtual environment at ./$VENV_DIR/"
else
    info "Virtual environment already exists at ./$VENV_DIR/"
fi

# Activate
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate" 2>/dev/null || source "$VENV_DIR/Scripts/activate" 2>/dev/null || {
    fatal "Could not activate virtual environment at $VENV_DIR. Check your shell."
}

# ---------------------------------------------------------------------------
# 3. Install requirements.txt
# ---------------------------------------------------------------------------
echo ""
echo "→ Installing dependencies..."

if [ -f "requirements.txt" ]; then
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
    info "Dependencies installed from requirements.txt"
else
    fatal "requirements.txt not found. Are you running setup.sh from the outputs/ directory?"
fi

# ---------------------------------------------------------------------------
# 4. Create ~/.clawbro/ directory
# ---------------------------------------------------------------------------
echo ""
echo "→ Creating ClawBro data directory..."

mkdir -p "$CLAWBRO_DIR"
info "Data directory: $CLAWBRO_DIR"

# ---------------------------------------------------------------------------
# 5. Initialize the SQLite database
# ---------------------------------------------------------------------------
echo ""
echo "→ Initialising database..."

"$PYTHON" -c "
import sys
sys.path.insert(0, 'src')
from memory import init_db
init_db('$DB_PATH')
print('  ✓ Database initialised: $DB_PATH')
"

# ---------------------------------------------------------------------------
# 6. Copy .env.example → .env and prompt for ANTHROPIC_API_KEY
# ---------------------------------------------------------------------------
echo ""
echo "→ Configuring environment..."

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        info "Created .env from .env.example"
    else
        warn ".env.example not found; creating a minimal .env"
        echo "ANTHROPIC_API_KEY=" > .env
    fi

    echo ""
    echo "  An Anthropic API key is required to use ClawBro."
    echo "  Get one at: https://console.anthropic.com/settings/keys"
    echo ""
    read -rp "  Enter your ANTHROPIC_API_KEY (or press Enter to set it later): " entered_key

    if [ -n "$entered_key" ]; then
        # Replace the placeholder in .env
        if command -v sed &>/dev/null; then
            sed -i "s|ANTHROPIC_API_KEY=your_key_here|ANTHROPIC_API_KEY=$entered_key|" .env
            info "API key saved to .env"
        else
            echo "ANTHROPIC_API_KEY=$entered_key" >> .env
            info "API key appended to .env"
        fi
    else
        warn "No key entered. Edit .env and set ANTHROPIC_API_KEY before running ClawBro."
    fi
else
    info ".env already exists — skipping key prompt."
fi

# ---------------------------------------------------------------------------
# 7. Print success message and next steps
# ---------------------------------------------------------------------------
echo ""
echo "═══════════════════════════════════"
echo "  ClawBro setup complete!"
echo "═══════════════════════════════════"
echo ""
echo "  Next steps:"
echo "    1. Activate the virtual environment:"
if [[ "$OSTYPE" == "msys"* ]] || [[ "$OSTYPE" == "win32"* ]]; then
    echo "         .venv\\Scripts\\activate"
else
    echo "         source .venv/bin/activate"
fi
echo "    2. Start ClawBro:"
echo "         python src/main.py"
echo ""
echo "  Optional:"
echo "    - Edit .env to configure Telegram, Discord, or Ollama."
echo "    - See README.md for full documentation."
echo ""
