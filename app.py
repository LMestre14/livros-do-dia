from flask import Flask, jsonify, request, send_from_directory
import requests
import os

app = Flask(__name__, static_folder="static")

AJAX_URL = "https://feiradolivrodelisboa.pt/_fll/wp-admin/admin-ajax.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Referer": "https://feiradolivrodelisboa.pt/",
}
LIMIT = 100  # Max per request (tested and works)




def fetch_books(offset=0, day=None, search=None):
    """Fetch books from getSearchedBooks endpoint."""
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
    """Fetch books with pagination, optional date filter and optional search."""
    try:
        offset = int(request.args.get("offset", 0))
        day = request.args.get("day") or None       # Optional: YYYY-MM-DD
        search = request.args.get("search") or None  # Optional: free-text

        raw_books = fetch_books(offset=offset, day=day, search=search)
        books = [normalise_book(b) for b in raw_books]

        return jsonify({
            "ok": True,
            "books": books,
            "count": len(books),
            "offset": offset,
            "has_more": len(books) == LIMIT,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/dates")
def api_dates():
    """Derive available fair dates dynamically from the first page of books."""
    try:
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐  Open http://localhost:{port} in your browser")
    app.run(debug=False, port=port)
