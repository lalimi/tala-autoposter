"""The BlackSea marketplace ("Знахідки") as material for product promotion posts.

The marketplace exposes its search as JSON (`/products/search?from=N`, 36 per
page; 2 174 products from 442 authors on 20.11.2026). The search payload cuts
descriptions at ~100 characters, so the product actually promoted is read in
full from its own page, where the same React component data is embedded.

Which product goes next is decided here, not by the model:
  * paid products with a real cover and a description worth retelling;
  * nothing promoted in the last PROMO_REPEAT_DAYS;
  * authors take turns (the two largest have 90 and 84 products and would
    otherwise fill the feed), the author promoted longest ago goes first;
  * within an author, rated products first.
The promoted product is recorded in {prefix}_posts.topic as
"promo:<product id>:<seller id>", so no extra table is needed.
"""
from __future__ import annotations

import html
import json
import logging
import re
import time
from pathlib import Path

import requests

import store
from config import settings

logger = logging.getLogger("tala")

SEARCH_URL = "https://blacksea.in.ua/products/search"
CACHE_MAX_AGE_H = 24
PROMO_REPEAT_DAYS = 120
MIN_DESCRIPTION_CHARS = 150
_HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 (blacksea-autoposter)"}

# Topics a brand account should not push to cold readers on its own initiative:
# trading/crypto "signals" and gambling read as financial promises, adult
# content is out of place. They stay on the marketplace, just not in promos.
_DENY_RE = re.compile(
    r"крипт|біткоїн|bitcoin|forex|форекс|трейд|сигнал|казино|ставк|беттинг|"
    r"18\+|еротик|інтим|nsfw", re.IGNORECASE)


def _cache_path(prefix: str) -> Path:
    return settings.BASE_DIR / "data" / f"{prefix}_catalog.json"


def fetch_catalog(prefix: str = "blacksea") -> list[dict]:
    """Every marketplace product, cached on disk for CACHE_MAX_AGE_H."""
    path = _cache_path(prefix)
    try:
        if path.exists() and time.time() - path.stat().st_mtime < CACHE_MAX_AGE_H * 3600:
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # a broken cache is refetched, not fatal
        pass
    products, frm, total = [], 0, None
    while total is None or frm < total:
        r = requests.get(SEARCH_URL, params={"from": frm}, headers=_HEADERS, timeout=30)
        r.raise_for_status()
        d = r.json()
        total = d.get("total") or 0
        page = d.get("products") or []
        if not page:
            break
        products += page
        frm += len(page)
        time.sleep(0.3)
    seen, out = set(), []
    for p in products:
        if p.get("id") not in seen:
            seen.add(p.get("id"))
            out.append(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    logger.info("catalog: %d products cached", len(out))
    return out


# Below this the price reads as a test or a mistake: 1,95 грн came up first
# among the clipart in a dry run. The marketplace's lower quartile is ~40 грн.
MIN_PRICE_UAH = 20


def _mostly_cyrillic(text: str) -> bool:
    """The audience reads Ukrainian; an English-only listing (AI clipart from
    abroad) would read as spam in this feed."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    return sum("а" <= c.lower() <= "я" or c.lower() in "іїєґ" for c in letters) / len(letters) >= 0.5


def _eligible(p: dict) -> bool:
    thumb = p.get("thumbnail_url") or ""
    name = (p.get("name") or "").strip()
    text = f"{name} {p.get('description') or ''}"
    return ((p.get("price_cents") or 0) >= MIN_PRICE_UAH * 100
            and thumb.startswith("http") and "default-avatar" not in thumb
            and len(name) >= 4
            and _mostly_cyrillic(text)
            and not _DENY_RE.search(text))


def _promo_history(prefix: str) -> tuple[set[str], dict[str, float]]:
    """Product ids promoted within PROMO_REPEAT_DAYS, and when each seller was
    last promoted (epoch)."""
    rows = store._req("GET", f"{prefix}_posts", params={
        "select": "topic,created_at", "topic": "like.promo:*",
        "order": "created_at.desc", "limit": 3000,
    }) or []
    cutoff = time.time() - PROMO_REPEAT_DAYS * 86400
    recent, seller_last = set(), {}
    for r in rows:
        parts = (r.get("topic") or "").split(":")
        if len(parts) < 3:
            continue
        ts = store._iso_to_epoch(r["created_at"])
        if ts >= cutoff:
            recent.add(parts[1])
        seller_last[parts[2]] = max(seller_last.get(parts[2], 0), ts)
    return recent, seller_last


def promo_queue(catalog: list[dict], prefix: str = "blacksea") -> list[dict]:
    """Eligible products in promotion order: one per author per round, the
    author promoted longest ago (or never) first, rated products first."""
    recent, seller_last = _promo_history(prefix)
    by_seller: dict[str, list[dict]] = {}
    for p in catalog:
        if _eligible(p) and p.get("id") not in recent:
            by_seller.setdefault(str(p["seller"]["id"]), []).append(p)

    def score(p):
        rt = p.get("ratings") or {}
        return ((rt.get("count") or 0) * (rt.get("average") or 0),
                len(p.get("description") or ""))

    for items in by_seller.values():
        items.sort(key=score, reverse=True)
    sellers = sorted(by_seller, key=lambda s: (seller_last.get(s, 0),
                                              -score(by_seller[s][0])[0]))
    queue, depth = [], 0
    while True:
        layer = [by_seller[s][depth] for s in sellers if len(by_seller[s]) > depth]
        if not layer:
            return queue
        queue += layer
        depth += 1


def _page(url: str) -> tuple[dict, str]:
    """The product page's embedded component data and its marketplace
    category (from the BreadcrumbList, e.g. "Навчання та освіта")."""
    r = requests.get(url, headers={"User-Agent": _HEADERS["User-Agent"]}, timeout=30)
    r.raise_for_status()
    comp = {}
    m = re.search(r'<script[^>]*data-component-name="ProfileProductPage"[^>]*>(.*?)</script>',
                  r.text, re.S)
    if m:
        try:
            comp = json.loads(m.group(1))
        except ValueError:
            comp = json.loads(html.unescape(m.group(1)))
    category = ""
    for ld in re.findall(r'<script type="application/ld\+json">(.*?)</script>', r.text, re.S):
        try:
            d = json.loads(ld)
        except ValueError:
            continue
        if d.get("@type") == "BreadcrumbList":
            items = d.get("itemListElement") or []
            if len(items) >= 3:
                category = (items[-2].get("name") or "").strip()
    return comp, category


def _plain(html_text: str) -> str:
    t = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", html_text or "")
    t = re.sub(r"<li[^>]*>", "• ", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def product_details(p: dict) -> dict | None:
    """Full data for one marketplace product, or None when its page has too
    little to say about it."""
    url = p["url"]
    comp, category = _page(url.split("?")[0])
    prod = comp.get("product") or {}
    desc = _plain(prod.get("description_html") or "") or (p.get("description") or "")
    if len(desc) < MIN_DESCRIPTION_CHARS:
        return None
    rt = prod.get("ratings") or p.get("ratings") or {}
    return {
        "id": p["id"],
        "seller_id": str(p["seller"]["id"]),
        "seller": p["seller"]["name"],
        "name": (prod.get("name") or p["name"]).strip(),
        "price": (p.get("price_cents") or 0) / 100,
        "pwyw": bool(p.get("is_pay_what_you_want")),
        "recurrence": p.get("recurrence"),
        "type": p.get("native_type"),
        "summary": (prod.get("summary") or "").strip(),
        "description": desc[:1500],
        "ratings_count": rt.get("count") or 0,
        "ratings_average": rt.get("average") or 0,
        "image_url": p.get("thumbnail_url"),
        "category": category,
        # The marketplace's own link: the sale counts as one the platform
        # brought (15% instead of 10%), which is what this traffic is.
        "url": url,
    }


def next_promo(prefix: str = "blacksea", tries: int = 6) -> dict | None:
    """The next product to promote, with its full page data, or None."""
    try:
        queue = promo_queue(fetch_catalog(prefix), prefix)
    except Exception as exc:
        logger.warning("catalog unavailable: %s", exc)
        return None
    for p in queue[:tries]:
        try:
            d = product_details(p)
        except Exception as exc:
            logger.info("promo: %s unreadable (%s)", p.get("url"), str(exc)[:80])
            continue
        if d:
            return d
        logger.info("promo: %s skipped, description too short", p.get("url"))
    return None


def as_fact(d: dict) -> dict:
    """The product in the shape the writer's guards read figures from: every
    number in it (price, ratings, page counts in the description) is allowed."""
    price = ("плати скільки хочеш, від " if d["pwyw"] else "") + f"{d['price']:g} грн"
    if d.get("recurrence"):
        price += f" ({d['recurrence']})"
    lines = [f"назва: {d['name']}", f"автор: {d['seller']}", f"ціна: {price}"]
    if d["ratings_count"] >= 3:
        lines.append(f"оцінка: {d['ratings_average']:g} з 5, відгуків: {d['ratings_count']}")
    if d.get("summary"):
        lines.append(f"коротко: {d['summary']}")
    lines.append(f"опис від автора:\n{d['description']}")
    return {"id": None, "text": "\n".join(lines), "detail": None}
