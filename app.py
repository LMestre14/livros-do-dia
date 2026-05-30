from flask import Flask, jsonify, request, send_from_directory
import requests
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__, static_folder="static")

AJAX_URL = "https://feiradolivrodelisboa.pt/_fll/wp-admin/admin-ajax.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Referer": "https://feiradolivrodelisboa.pt/",
}
LIMIT = 100  # Max per request (tested and works)

# ── Enrichment data (category + synopsis from Bertrand) ──────────────────────
def _load_enrichment():
    path = os.path.join(os.path.dirname(__file__), "enrichment.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        print(f"📖 Enrichment loaded: {len(data)} entries")
        return data
    print("ℹ️  No enrichment.json found — run build_enrichment.py to generate it")
    return {}

_enrichment = _load_enrichment()

# ── In-memory cache ──────────────────────────────────────────────────────────
_cache = {"books": [], "publishers": [], "categories": [], "ready": False}
_cache_lock = threading.Lock()


def _fetch_page(offset):
    """Fetch a single page of all livros-do-dia (no day/search filter)."""
    params = {
        "action": "getSearchedBooks",
        "livros-do-dia": "1",
        "invisuais": "0",
        "offset": offset,
        "limit": LIMIT,
    }
    try:
        r = requests.get(AJAX_URL, params=params, headers=HEADERS, timeout=15)
        if r.status_code == 204 or not r.text or r.text.strip() in ("", "0"):
            return []
        return r.json()
    except Exception as e:
        print(f"Error fetching page at offset {offset}: {e}")
        return []


def _populate_cache():
    """Fetch all livros-do-dia in parallel and store normalised books in RAM."""
    try:
        print("🔄 Populating book cache…")
        first = _fetch_page(0)
        if not first:
            print("❌ Cache: first page returned nothing")
            return

        all_raw = list(first)
        offsets = list(range(100, 7100, 100))  # overshoot; empty pages are ignored

        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(_fetch_page, o): o for o in offsets}
            for f in as_completed(futures):
                batch = f.result()
                if batch:
                    all_raw.extend(batch)

        normalised = [normalise_book(b) for b in all_raw]

        # Merge enrichment data (category, parent_category, synopsis) by ISBN
        for book in normalised:
            enc = _enrichment.get(book["isbn"], {})
            book["category"]        = enc.get("category", "")
            book["parent_category"] = enc.get("parent_category", "")
            book["synopsis"]        = enc.get("synopsis", "")

        publishers = sorted({b["publisher"] for b in normalised if b["publisher"]})
        categories = sorted({b["category"]  for b in normalised if b["category"]})

        with _cache_lock:
            _cache["books"]      = normalised
            _cache["publishers"] = publishers
            _cache["categories"] = categories
            _cache["ready"]      = True

        print(f"✅ Cache ready: {len(normalised)} books, {len(publishers)} publishers, {len(categories)} categories")
    except Exception as e:
        print(f"❌ Cache populate failed: {e}")


def fetch_books(offset=0, day=None, search=None):
    """Fetch books from getSearchedBooks endpoint (live fallback)."""
    params = {
        "action": "getSearchedBooks",
        "livros-do-dia": "1",
        "invisuais": "0",
        "offset": offset,
        "limit": LIMIT,
    }
    if day:
        params["day"] = day
    if search:
        params["search"] = search
    try:
        r = requests.get(AJAX_URL, params=params, headers=HEADERS, timeout=15)
        if r.status_code == 204 or not r.text or r.text.strip() in ("", "0"):
            return []
        return r.json()
    except Exception as e:
        print(f"Error fetching books: {e}")
        return []


def normalise_book(raw):
    """Normalise raw book data into clean format."""
    pvp = float(raw.get("pvp") or 0)
    pvp_feira = float(raw.get("pvp_feira") or 0)
    pvp_dia = float(raw.get("pvp_dia") or raw.get("pvp_livro_do_dia") or 0)
    dates_raw = raw.get("livro_do_dia_datas") or []
    if isinstance(dates_raw, list):
        dates = [str(d).strip() for d in dates_raw if d]
    else:
        dates = [d.strip() for d in str(dates_raw).split(",") if d.strip()]

    pid = str(raw.get("participante_id") or "")
    stand = raw.get("stand") or ""

    return {
        "id": f"{pid}-{raw.get('isbn', '')}",
        "isbn": raw.get("isbn") or "",
        "title": raw.get("post_title") or raw.get("titulo") or "",
        "author": raw.get("autor") or "",
        "publisher": raw.get("participant_name") or raw.get("participante_name") or "",
        "chancela": raw.get("chancela") or "",
        "stand": stand,
        "pvp": round(pvp, 2),
        "pvp_feira": round(pvp_feira, 2),
        "pvp_dia": round(pvp_dia, 2),
        "dates": dates,
        "cover_jpg": raw.get("cover_jpg") or "",
        "cover_webp": raw.get("cover_webp") or "",
    }


@app.route("/api/books")
def api_books():
    """Fetch books with pagination, optional date/search/publisher filters."""
    try:
        offset = int(request.args.get("offset", 0))
        day       = request.args.get("day")       or None
        search    = request.args.get("search")    or None
        publisher = request.args.get("publisher") or None

        if _cache["ready"]:
            books = _cache["books"]
            if day:
                books = [b for b in books if day in b["dates"]]
            if search:
                q = search.lower()
                books = [b for b in books if q in b["title"].lower() or q in b["author"].lower()]
            if publisher:
                books = [b for b in books if b["publisher"] == publisher]
            category = request.args.get("category") or None
            if category:
                books = [b for b in books if b["category"] == category]
            total = len(books)
            page  = books[offset: offset + LIMIT]
            return jsonify({
                "ok": True, "books": page, "count": len(page),
                "offset": offset, "has_more": offset + LIMIT < total,
            })

        # Fallback: cache not yet ready → live API (no publisher filter available)
        raw_books = fetch_books(offset=offset, day=day, search=search)
        books = [normalise_book(b) for b in raw_books]
        return jsonify({
            "ok": True, "books": books, "count": len(books),
            "offset": offset, "has_more": len(books) == LIMIT,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/publishers")
def api_publishers():
    """Return sorted list of all publisher names (from cache)."""
    return jsonify({"ok": True, "publishers": _cache["publishers"]})


@app.route("/api/categories")
def api_categories():
    """Return sorted list of all category names (from enrichment cache)."""
    return jsonify({"ok": True, "categories": _cache["categories"]})


@app.route("/api/dates")
def api_dates():
    """Derive available fair dates from cache (or first live page as fallback)."""
    try:
        if _cache["ready"]:
            all_dates = set()
            for b in _cache["books"]:
                all_dates.update(b["dates"])
            return jsonify({"ok": True, "dates": sorted(all_dates)})
        raw_books = fetch_books(offset=0)
        all_dates = set()
        for b in raw_books:
            datas = b.get("livro_do_dia_datas") or []
            if isinstance(datas, list):
                all_dates.update(str(d).strip() for d in datas if d)
            else:
                all_dates.update(d.strip() for d in str(datas).split(",") if d.strip())
        return jsonify({"ok": True, "dates": sorted(all_dates)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/book/<path:book_id>")
def api_book(book_id):
    """Fetch a single book's full details (including exact stand list) via getBooksByID."""
    try:
        r = requests.get(AJAX_URL, params={"action": "getBooksByID", "id": book_id},
                         headers=HEADERS, timeout=15)
        if r.status_code != 200 or not r.text.strip() or r.text.strip() == "0":
            return jsonify({"ok": False, "error": "not found"}), 404
        books = r.json()
        if not books:
            return jsonify({"ok": False, "error": "not found"}), 404
        return jsonify({"ok": True, "book": normalise_book(books[0])})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/sw.js")
def sw():
    return send_from_directory("static", "sw.js", mimetype="application/javascript")

@app.route("/manifest.json")
def manifest():
    return send_from_directory("static", "manifest.json", mimetype="application/manifest+json")


# Start background cache population immediately at import time
threading.Thread(target=_populate_cache, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐  Open http://localhost:{port} in your browser")
    app.run(debug=False, port=port)
