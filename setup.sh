#!/usr/bin/env zsh
set -e

# ── Config ────────────────────────────────────────────────────────────────────
REPO_NAME="livros-do-dia"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "📂  Project: $PROJECT_DIR"
echo ""

# ── 1. Stage & commit all files ───────────────────────────────────────────────
echo "🔧  Staging all files..."
cd "$PROJECT_DIR"
git add .
git commit -m "Add full app: Flask backend, PWA, Render deploy config" || echo "   (nothing new to commit)"

# ── 2. Create GitHub repo & push ──────────────────────────────────────────────
echo ""
echo "🐙  Creating GitHub repository '$REPO_NAME'..."
gh repo create "$REPO_NAME" \
  --public \
  --description "Livros do Dia — Feira do Livro de Lisboa 2026" \
  --source="$PROJECT_DIR" \
  --remote=origin \
  --push

REPO_URL=$(gh repo view "$REPO_NAME" --json url -q .url)
echo "   ✅  Repository live at: $REPO_URL"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅  On GitHub: $REPO_URL"
echo ""
echo "   Next → deploy to Render:"
echo "   1. Go to https://render.com and sign in"
echo "   2. New > Web Service > connect '$REPO_NAME'"
echo "   3. Build command:  pip install -r requirements.txt"
echo "   4. Start command:  gunicorn app:app"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
