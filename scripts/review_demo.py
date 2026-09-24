"""Walk-through of every Threads permission, for the Meta app-review screencast.

Meta wants a recording that starts logged out, shows the Threads login and
consent screen, then each permission in use together with what the app does
with the data. The autoposter has no UI — it is a set of server jobs — so this
script is that UI: run it locally while recording and it makes the same API
calls as the jobs, one captioned step at a time.

    python3 scripts/review_demo.py

Log in as @blacksea.in.ua. With standard access, keyword search returns only
the account's own posts and profile lookup only official Meta accounts
(checked 24.09.2026). So the queries below are Ukrainian ones that return
results for that account ("digital products" in English returns nothing), and
the profile step looks up @threads and @instagram.

The login link goes to the clipboard rather than the default browser: it is
meant for a private window, so the recording starts logged out (as Meta asks)
and the browser's own Instagram or Threads session cannot pick the wrong
account. The app secret is read with getpass, so it never appears on screen or
in the recording. Only the standard library is used, so it runs on a stock
macOS Python.

It requests the same scopes as scripts/reauth.py. debug_token reports the
account's grant rather than the token's, so a narrower consent might narrow
the grant the server's token relies on — and chains are published as replies,
which need threads_manage_replies.

The redirect URI below must be registered in the Meta app under
Use cases → Threads API → Settings → Redirect Callback URLs.
"""
from __future__ import annotations

import getpass
import json
import secrets
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request

REDIRECT_URI = "https://lalimi.github.io/blacksea-privacy/callback.html"
GRAPH = "https://graph.threads.net"
AUTHORIZE = "https://threads.net/oauth/authorize"
# The Threads app id is public (it appears in every authorize URL).
APP_ID = "1672328520867855"
SCOPES = [
    "threads_basic", "threads_content_publish", "threads_manage_insights",
    "threads_manage_replies", "threads_read_replies",
    "threads_delete", "threads_keyword_search", "threads_profile_discovery",
]
# (query, its meaning for the reviewer). Our audience is Ukrainian.
KEYWORDS = [
    ("перший продаж", "first sale"),
    ("цифрові продукти", "digital products"),
    ("Notion", "Notion templates"),
]
PROFILES = ["threads", "instagram"]
METRICS = ["views", "likes", "replies", "reposts", "quotes"]
POST_TEXT = ("Test post from BlackSea's publishing tool, recorded for Meta app review. "
             "It will be deleted in a minute.")
REPLY_TEXT = ("Test reply from BlackSea's publishing tool, recorded for Meta app review. "
              "In production the app replies with practical advice to posts that ask "
              "a question we can help with. "
              "This reply will be deleted in a minute.")


def api(method: str, path: str, token: str | None = None, soft: bool = False,
        **params) -> dict:
    """Call the Graph API. An error ends the demo with Meta's message, unless
    `soft`, where it comes back as {"error": ...} for the caller to show."""
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
        if soft:
            return {"error": body[:200]}
        sys.exit(f"\n  API error {e.code} on {method} {path}:\n  {body[:400]}")


def step(n: int, title: str, permission: str) -> None:
    perm = textwrap.fill(permission, 64, initial_indent="  permission: ",
                         subsequent_indent=" " * 14)
    print(f"\n{'=' * 64}\nStep {n}. {title}\n{perm}\n{'=' * 64}")


def pause(msg: str = "Press Enter to continue…") -> None:
    input(f"\n  {msg}")


def ask_yes(msg: str) -> bool:
    return input(f"\n  {msg} [y/N] ").strip().lower() in ("y", "yes", "т", "так")


def to_clipboard(text: str) -> bool:
    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def short(text: str | None, width: int = 80) -> str:
    return textwrap.shorten(" ".join((text or "").split()), width, placeholder="…")


def publish(token: str, text: str, reply_to_id: str | None = None) -> str:
    """Create a text container, wait until it is ready, publish it — the same
    sequence as the production publisher. Returns the new media id."""
    params = {"media_type": "TEXT", "text": text}
    if reply_to_id:
        params["reply_to_id"] = reply_to_id
    creation_id = api("POST", "/v1.0/me/threads", token, **params)["id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        status = api("GET", f"/v1.0/{creation_id}", token, fields="status,error_message")
        if status.get("status") == "FINISHED":
            break
        if status.get("status") == "ERROR":
            sys.exit(f"\n  Container error: {status.get('error_message')}")
        time.sleep(2)
    return api("POST", "/v1.0/me/threads_publish", token, creation_id=creation_id)["id"]


def permalink(token: str, media_id: str) -> str:
    return api("GET", f"/v1.0/{media_id}", token, fields="permalink").get("permalink", "")


def show_link(what: str, link: str) -> None:
    """Print a new post's link and put it on the clipboard for the browser."""
    print(f"  ✓ {what} published: {link}")
    if link and to_clipboard(link):
        print("  ✓ Link copied — paste it into the browser to show it.")


def login(app_secret: str) -> str:
    step(1, "Log in with Threads and grant access (OAuth)", ", ".join(SCOPES))
    url = AUTHORIZE + "?" + urllib.parse.urlencode({
        "client_id": APP_ID, "redirect_uri": REDIRECT_URI, "scope": ",".join(SCOPES),
        "response_type": "code", "state": secrets.token_urlsafe(12),
    })
    print("  Open the login link in a private browser window, so the demo starts\n"
          "  logged out of Threads.")
    if to_clipboard(url):
        print("  ✓ Link copied — paste it into the private window's address bar.")
    print(f"\n  {url}")
    code = input("\n  Paste the authorization code shown after granting access: ")
    tok = api("POST", "/oauth/access_token", client_id=APP_ID, client_secret=app_secret,
              grant_type="authorization_code", redirect_uri=REDIRECT_URI,
              code=code.strip().removesuffix("#_"))
    print("  ✓ Access token received — the account is connected.")
    return tok["access_token"]


def show_profile(token: str) -> None:
    step(2, "Read the connected account's profile", "threads_basic")
    me = api("GET", "/v1.0/me", token, fields="id,username,name,threads_biography")
    print(f"  Connected account: @{me.get('username')} ({me.get('name', '')})")
    print(f"  Account ID: {me.get('id')}")
    if me.get("threads_biography"):
        print(f"  Bio: {short(me['threads_biography'])}")
    print("  The app publishes only to accounts our business owns.")
    pause()


def search_niche(token: str) -> list[dict]:
    """Show the search results; return the top post of each keyword."""
    step(3, "Search public posts in our niche", "threads_keyword_search")
    print("  Our audience is Ukrainian creators, so we search Ukrainian keywords,\n"
          "  most popular posts first. (With standard access Meta returns only our\n"
          "  own account's posts; once approved, search covers all public posts.)")
    found: list[dict] = []
    for query, meaning in KEYWORDS:
        posts = api("GET", "/v1.0/keyword_search", token, q=query, search_type="TOP",
                    fields="id,text,timestamp,username,permalink,is_reply",
                    limit=10).get("data", [])
        # Our own results include the continuation parts of our chains, which
        # read as fragments and have almost no views of their own.
        posts = [p for p in posts if not p.get("is_reply")]
        print(f"\n  “{query}” ({meaning}) — {len(posts)} top posts:")
        for p in posts[:3]:
            print(f"    • @{p.get('username')}: {short(p.get('text'), 70)}")
            print(f"      {p.get('timestamp', '')[:10]}  {p.get('permalink', '')}")
        if posts and posts[0]["id"] not in {f["id"] for f in found}:
            found.append(posts[0])
    print("\n  What the app does with the results:\n"
          "   1. Our drafting step reads which questions people ask and writes\n"
          "      original posts for our account that answer them.\n"
          "   2. When a post asks something we can help with, the app replies\n"
          "      to it from our brand account (next step).\n"
          "  We never send private messages, never tag authors and never\n"
          "  republish their posts.")
    pause()
    return found


def reply_to_found(token: str, post: dict | None) -> str | None:
    step(4, "Reply to a post found by search",
         "threads_keyword_search, threads_manage_replies, threads_content_publish")
    if not post:
        print("  Search returned no posts, so there is nothing to reply to.")
        return None
    print(f"  Post: {short(post.get('text'), 76)}\n        {post.get('permalink', '')}")
    print("\n  Reply drafted by the app:\n    "
          + textwrap.fill(REPLY_TEXT, 72, subsequent_indent="    "))
    if not ask_yes("Publish this reply under the post now?"):
        return None
    reply_id = publish(token, REPLY_TEXT, reply_to_id=post["id"])
    show_link("Reply", permalink(token, reply_id))
    pause("Show the reply in the browser, then press Enter…")
    return reply_id


def lookup_profiles(token: str) -> None:
    step(5, "Look up public creator profiles", "threads_profile_discovery")
    print("  Once a week the app looks up a short list of public creator accounts\n"
          "  in our niche and compares their public numbers with the week before,\n"
          "  to see which creators and topics are growing and whom to invite to\n"
          "  collaborate. (With standard access only official Meta accounts can be\n"
          "  looked up, so the demo uses them.)\n")
    print(f"  {'account':<13}{'followers':>12}{'views 7d':>11}{'likes 7d':>10}{'reposts 7d':>12}")
    for username in PROFILES:
        p = api("GET", "/v1.0/profile_lookup", token, username=username)
        print(f"  @{p.get('username', username):<12}{p.get('follower_count') or 0:>12,}"
              f"{p.get('views_count') or 0:>11,}{p.get('likes_count') or 0:>10,}"
              f"{p.get('reposts_count') or 0:>12,}")
    print("\n  We read only public numbers and never send these accounts messages.")
    pause()


def publish_own(token: str) -> str | None:
    step(6, "Publish a post to our own account", "threads_content_publish")
    print(f"  Post text:\n    {textwrap.fill(POST_TEXT, 72, subsequent_indent='    ')}")
    if not ask_yes("Publish this post to the connected account now?"):
        return None
    media_id = publish(token, POST_TEXT)
    show_link("Post", permalink(token, media_id))
    pause("Show the live post in the browser, then press Enter…")
    return media_id


def show_insights(token: str, posts: list[tuple[str, str]]) -> None:
    step(7, "Read the performance of our own posts", "threads_manage_insights")
    print(f"  {'post':<24}" + "".join(f"{m:>9}" for m in METRICS))
    for label, media_id in posts:
        # Soft: a post only seconds old may not have insights yet, and an error
        # here must not end the demo before the test posts are deleted.
        res = api("GET", f"/v1.0/{media_id}/insights", token, soft=True,
                  metric=",".join(METRICS))
        if "error" in res:
            print(f"  {label:<24}  not available yet")
            continue
        values = {m["name"]: (m.get("values") or [{}])[0].get("value", 0)
                  for m in res.get("data", [])}
        print(f"  {label:<24}" + "".join(f"{values.get(m, 0):>9,}" for m in METRICS))
    print("\n  We read these daily to learn which topics and posting times work\n"
          "  for our audience. A brand-new post starts at zero.")
    pause()


def delete_test_posts(token: str, posts: list[tuple[str, str]]) -> None:
    step(8, "Delete our test reply and post", "threads_delete")
    print("  Used to remove our own posts that contain a mistake.")
    if not posts:
        print("  Nothing was published, so there is nothing to delete.")
        return
    for label, media_id in posts:
        api("DELETE", f"/v1.0/{media_id}", token)
        print(f"  ✓ {label} deleted.")
    pause("Refresh their browser tabs to show they are gone, then press Enter…")


def main() -> None:
    print("BlackSea — Threads publishing tool\n"
          "Walk-through of every permission requested in app review.\n"
          f"\n  Threads app ID: {APP_ID}")
    app_secret = getpass.getpass("  Threads app secret (hidden): ").strip()
    token = login(app_secret)
    show_profile(token)
    found = search_niche(token)
    reply_id = reply_to_found(token, found[0] if found else None)
    lookup_profiles(token)
    post_id = publish_own(token)
    measured = [(f"post of {p.get('timestamp', '')[:10]}", p["id"]) for p in found]
    if post_id:
        measured.append(("test post (just now)", post_id))
    if measured:
        show_insights(token, measured)
    delete_test_posts(token, [(label, mid) for label, mid in (
        ("Test reply", reply_id), ("Test post", post_id)) if mid])
    print("\nDone. Every requested permission has been demonstrated.")


if __name__ == "__main__":
    main()
