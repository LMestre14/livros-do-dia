#!/usr/bin/env python3
"""
Build enrichment.json — run ONCE locally to scrape Wook.pt for category + synopsis.

Usage:
    python3 build_enrichment.py

Creates/updates enrichment.json in the same directory.
Safe to interrupt and re-run — already-processed ISBNs are skipped.
"""
import requests, re, json, time, os
from concurrent.futures import ThreadPoolExecutor, as_completed

FEIRA_URL = "https://feiradolivrodelisboa.pt/_fll/wp-admin/admin-ajax.php"
FEIRA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Referer": "https://feiradolivrodelisboa.pt/",
}
WOOK_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "pt-PT,pt;q=0.9",
}
OUTPUT_FILE = "enrichment.json"
WORKERS = 5
CHECKPOINT_EVERY = 50


def fetch_all_isbns():
    print("📚 Fetching all ISBNs from Feira API…")

    def fetch_page(offset):
        try:
            r = requests.get(FEIRA_URL, params={
                "action": "getSearchedBooks", "livros-do-dia": "1",
                "invisuais": "0", "offset": offset, "limit": 100,
            }, headers=FEIRA_HEADERS, timeout=15)
            if not r.ok or r.text.strip() in ("", "0"):
                return []
            return r.json()
        except:
            return []

    first = fetch_page(0)
    if not first:
        print("❌ Could not fetch first page"); return []

    all_raw = list(first)
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(fetch_page, o): o for o in range(100, 7100, 100)}
        for f in as_completed(futs):
            batch = f.result()
            if batch:
                all_raw.extend(batch)

    isbns = list({b["isbn"] for b in all_raw if b.get("isbn")})
    print(f"✅ Found {len(isbns)} unique ISBNs")
    return isbns


def fetch_wook(isbn):
    """Returns (isbn, dict) — dict is {} if book not found, None on network error."""
    try:
        # Wook search redirects directly to the product page when there's an exact ISBN match
        r = requests.get(f"https://www.wook.pt/pesquisa?keyword={isbn}",
                         headers=WOOK_HEADERS, timeout=12, allow_redirects=True)
        if r.status_code != 200:
            return isbn, {}
        html = r.text

        # Category — breadcrumb via itemprop="item" on arvoretematica links
        # Multiple breadcrumb trails can appear; take the first one (stops when position resets)
        items = re.findall(
            r'itemprop="item"[^>]*href="([^"]*arvoretematica[^"]*)"[^>]*>'
            r'.*?itemprop="name"[^>]*>\s*([^<]+?)\s*</span>'
            r'.*?itemprop="position"\s+content="(\d+)"',
            html, re.S
        )
        category = parent_category = ""
        crumb_trail = []
        last_pos = 0
        for _href, name, pos in items:
            p = int(pos)
            if p <= last_pos:   # position reset → second trail, stop
                break
            crumb_trail.append((p, name.strip()))
            last_pos = p

        crumb_trail.sort()
        # pos 2 = "Livros em Português" (top), pos 3 = parent, pos 4 = leaf
        if len(crumb_trail) >= 3:
            parent_category = crumb_trail[-2][1]
            category        = crumb_trail[-1][1]
        elif len(crumb_trail) == 2:
            parent_category = crumb_trail[0][1]
            category        = crumb_trail[1][1]
        elif len(crumb_trail) == 1:
            category = crumb_trail[0][1]

        # Synopsis — from JSON-LD Book description
        synopsis = ""
        for block in re.findall(
                r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                html, re.S | re.I):
            try:
                obj = json.loads(block)
                if obj.get("@type") == "Book" and obj.get("description"):
                    synopsis = obj["description"].strip()
                    break
            except:
                pass

        return isbn, {"category": category, "parent_category": parent_category, "synopsis": synopsis}
    except:
        return isbn, None



def main():
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            enrichment = json.load(f)
        print(f"📂 Loaded existing {OUTPUT_FILE} ({len(enrichment)} entries)")
    else:
        enrichment = {}

    all_isbns = fetch_all_isbns()
    if not all_isbns:
        return

    pending = [isbn for isbn in all_isbns if isbn not in enrichment]
    print(f"\n🔍 To process: {len(pending)}  (skipping {len(all_isbns) - len(pending)} already done)")
    if not pending:
        print("✅ All ISBNs already processed!"); return

    print(f"⏱  Estimated time: ~{len(pending) / WORKERS / 2 / 60:.0f} min at {WORKERS} workers")
    print(f"💾 Checkpoint every {CHECKPOINT_EVERY} books\n")

    done = errors = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_wook, isbn): isbn for isbn in pending}
        for f in as_completed(futs):
            isbn, data = f.result()
            if data is not None:
                enrichment[isbn] = data
            else:
                errors += 1
            done += 1
            elapsed = time.time() - start
            rate = done / elapsed
            remaining = (len(pending) - done) / rate if rate > 0 else 0
            print(f"\r  {done}/{len(pending)} ({done/len(pending)*100:.0f}%)  "
                  f"errors={errors}  {remaining/60:.1f} min left    ", end="", flush=True)
            if done % CHECKPOINT_EVERY == 0:
                with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
                    json.dump(enrichment, out, ensure_ascii=False)
                print(f"\n  💾 Checkpoint saved ({len(enrichment)} entries)", flush=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        json.dump(enrichment, out, ensure_ascii=False)

    total_time = time.time() - start
    size_mb = os.path.getsize(OUTPUT_FILE) / 1024 / 1024
    with_cat = sum(1 for d in enrichment.values() if d.get("category"))
    with_syn = sum(1 for d in enrichment.values() if d.get("synopsis"))
    print(f"\n\n✅ Done in {total_time/60:.1f} min  —  {len(enrichment)} books enriched")
    print(f"   With category: {with_cat} ({with_cat/len(enrichment)*100:.0f}%)")
    print(f"   With synopsis: {with_syn} ({with_syn/len(enrichment)*100:.0f}%)")
    print(f"   File size:     {size_mb:.2f} MB")
    print(f"\nNext: git add enrichment.json && git commit -m 'Add enrichment' && git push")


if __name__ == "__main__":
    main()
