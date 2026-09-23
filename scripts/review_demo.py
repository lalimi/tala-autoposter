"""Walk-through of every Threads permission, for the Meta app-review screencast.

Meta wants a recording that shows the OAuth login and each permission in use,
but the autoposter has no UI — it is a set of server jobs. This script is that
UI: run it locally while recording the screen and it goes through the whole
flow step by step, pausing so the reviewer can follow.

    python3 scripts/review_demo.py

It asks for the Threads app ID and secret (the secret is read with getpass, so
it never appears on screen or in the recording) and uses only the standard
library, so it runs on a stock macOS Python.

The redirect URI below must be registered in the Meta app under
Use cases → Threads API → Settings → Redirect Callback URLs.
"""
from __future__ import annotations

import getpass
import json
import secrets
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import Counter

REDIRECT_URI = "https://lalimi.github.io/blacksea-privacy/callback.html"
GRAPH = "https://graph.threads.net"
AUTHORIZE = "https://threads.net/oauth/authorize"
KEYWORDS = ["AI tools for creators", "digital products", "Notion template"]

# Words that say nothing about a topic, dropped when summarising results.
STOP = set("""a an and are as at be but by can do for from get has have how i if in
into is it its just me my no not of on or our so that the their them then there
these this to up was we what when which who why will with you your""".split())


def api(method: str, path: str, token: str | None = None, **params) -> dict:
    if token:
        params["access_token"] = token
    data = urllib.parse.urlencode(params)
    url = path if path.startswith("http") else f"{GRAPH}{path}"
    if method in ("GET", "DELETE"):
        # DELETE carries its parameters in the query string: a body on DELETE
        # is not reliably read by the Graph API.
        req = urllib.request.Request(f"{url}?{data}", method=method)
    else:
        req = urllib.request.Request(url, data=data.encode(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        sys.exit(f"\n  API error {e.code} on {method} {path}:\n  {body[:400]}")


def step(n: int, title: str, permission: str) -> None:
    print(f"\n{'=' * 64}\nStep {n}. {title}\n  permission: {permission}\n{'=' * 64}")


def pause(msg: str = "Press Enter to continue…") -> None:
    input(f"\n  {msg}")


def ask_yes(msg: str) -> bool:
    return input(f"\n  {msg} [y/N] ").strip().lower() in ("y", "yes", "т", "так")


def main() -> None:
    print("BlackSea — Threads publishing tool\n"
          "Demonstration of every permission requested in app review.")
    app_id = input("\n  Threads app ID: ").strip()
    app_secret = getpass.getpass("  Threads app secret (hidden): ").strip()
    with_delete = ask_yes("Is threads_delete added to the app's use case?")

    scopes = ["threads_basic", "threads_content_publish",
              "threads_manage_insights", "threads_keyword_search"]
    if with_delete:
        scopes.append("threads_delete")

    # --- OAuth --------------------------------------------------------------
    step(0, "Log in with Threads and grant access (OAuth)", ", ".join(scopes))
    state = secrets.token_urlsafe(12)
    url = AUTHORIZE + "?" + urllib.parse.urlencode({
        "client_id": app_id, "redirect_uri": REDIRECT_URI,
        "scope": ",".join(scopes), "response_type": "code", "state": state,
    })
    print("  Opening the Threads authorization screen in the browser…")
    webbrowser.open(url)
    print(f"  (if it did not open: {url})")
    code = input("\n  Paste the authorization code shown after granting access: ").strip()
    code = code.removesuffix("#_")
    tok = api("POST", "/oauth/access_token", client_id=app_id,
              client_secret=app_secret, grant_type="authorization_code",
              redirect_uri=REDIRECT_URI, code=code)
    token = tok["access_token"]
    print("  ✓ Access token received — the account is connected.")

    # --- threads_basic ------------------------------------------------------
    step(1, "Read the connected account's profile", "threads_basic")
    me = api("GET", "/v1.0/me", token, fields="id,username,name,threads_biography")
    print(f"  Connected account: @{me.get('username')} ({me.get('name', '')})")
    print(f"  Account ID: {me.get('id')}")
    pause()

    # --- threads_keyword_search ---------------------------------------------
    step(2, "Research what our niche is talking about", "threads_keyword_search")
    print("  We search public posts for our niche keywords, most popular first.\n"
          "  The results tell us which topics our next posts should address.")
    words: Counter[str] = Counter()
    for kw in KEYWORDS:
        res = api("GET", "/v1.0/keyword_search", token, q=kw, search_type="TOP",
                  fields="id,text,timestamp,username,permalink", limit=10)
        posts = res.get("data", [])
        print(f"\n  Keyword “{kw}” — {len(posts)} top posts:")
        for p in posts[:5]:
            text = " ".join((p.get("text") or "").split())
            print(f"    • {textwrap.shorten(text, 88, placeholder='…')}")
            print(f"      {p.get('timestamp', '')[:10]}  {p.get('permalink', '')}")
            words.update(w for w in (t.strip(".,!?:;()\"'«»—-").lower()
                                     for t in text.split())
                         if len(w) > 3 and w not in STOP)
    if words:
        print("\n  Recurring themes across the results (input for our content plan):")
        print("   ", ", ".join(w for w, _ in words.most_common(12)))
    print("\n  We never message or tag these authors and never republish their posts.")
    pause()

    # --- threads_content_publish --------------------------------------------
    step(3, "Publish a post to our own account", "threads_content_publish")
    default = ("Test post from BlackSea's publishing tool, recorded for Meta "
               "app review. It will be deleted in a minute.")
    print(f"  Post text:\n    {default}")
    if not ask_yes("Publish this post to the connected account now?"):
        print("  Skipped publishing — steps 4 and 5 need a published post.")
        return
    container = api("POST", "/v1.0/me/threads", token, media_type="TEXT", text=default)
    time.sleep(3)
    media_id = api("POST", "/v1.0/me/threads_publish", token,
                   creation_id=container["id"])["id"]
    post = api("GET", f"/v1.0/{media_id}", token, fields="permalink,timestamp")
    print(f"  ✓ Published: {post.get('permalink')}")
    pause("Open the link to show the live post, then press Enter…")

    # --- threads_manage_insights --------------------------------------------
    step(4, "Read the performance of our own post", "threads_manage_insights")
    ins = api("GET", f"/v1.0/{media_id}/insights", token,
              metric="views,likes,replies,reposts,quotes")
    for m in ins.get("data", []):
        vals = m.get("values") or [{}]
        print(f"  {m['name']:>8}: {vals[0].get('value', 0)}")
    print("  (a brand-new post starts at zero; we read these daily to see which\n"
          "   topics and posting times work for our audience)")
    pause()

    # --- threads_delete -----------------------------------------------------
    if with_delete:
        step(5, "Delete our own post", "threads_delete")
        print("  Used to remove our own posts that contain a mistake.")
        api("DELETE", f"/v1.0/{media_id}", token)
        print("  ✓ Post deleted.")
    else:
        print(f"\n  Remember to delete the test post manually: {post.get('permalink')}")

    print("\nDone. Every requested permission has been demonstrated.")


if __name__ == "__main__":
    main()
