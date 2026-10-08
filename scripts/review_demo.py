"""Walk-through of every Threads permission, for the Meta app-review screencast.

Meta wants a recording that starts logged out, shows the Threads login and
consent screen, then each permission in use together with what the app does
with the data. The autoposter has no UI — it is a set of server jobs — so this
script is that UI: it makes the same API calls as the jobs, one captioned step
at a time.

    python3 scripts/review_demo.py --record    # film it with glide, export an MP4
    python3 scripts/review_demo.py --auto      # same walk-through, no recording
    python3 scripts/review_demo.py             # press Enter between the steps

With --record the person only does what cannot be automated: paste the app
secret, log in to Threads, grant access and click “Copy code”. Everything else
runs by itself, with pauses long enough to read. It publishes a test reply and
a test post on the connected account and deletes both at the end, and it
refuses to go on if the account is not ACCOUNT.

Pages open with `open -a Safari`, which lands in the frontmost Safari window.
Make that a private window (⌘⇧N): it starts logged out, as Meta asks, and keeps
the personal Threads session out of the film. Dia, the default browser here,
ignores --incognito from the command line (checked 08.10.2026).

With standard access, keyword search returns only the account's own posts and
profile lookup only official Meta accounts (checked 24.09.2026). So the queries
below are Ukrainian ones that return results for that account ("digital
products" in English returns nothing), and the profile step looks up @threads
and @instagram.

The app secret is read with getpass, so it never appears on screen or in the
recording. Only the standard library is used, so it runs on a stock macOS
Python.

It requests the same scopes as scripts/reauth.py. debug_token reports the
account's grant rather than the token's, so a narrower consent might narrow
the grant the server's token relies on — and chains are published as replies,
which need threads_manage_replies.

The redirect URI below must be registered in the Meta app under
Use cases → Threads API → Settings → Redirect Callback URLs.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets
import select
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

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
POLICY_URL = "https://lalimi.github.io/blacksea-privacy/"
# The only account the demo may post to.
ACCOUNT = "blacksea.in.ua"
BROWSER = "Safari"
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
# An authorization code as the callback page puts it on the clipboard: one
# long token. A link, the only other long thing copied here, has "://" in it.
CODE_RE = re.compile(r"[^\s:/]{40,}")

# --auto / --record: after the login nothing waits for a key press.
AUTO = False


def api(method: str, path: str, token: str | None = None, soft: bool = False,
        **params) -> dict:
    """Call the Graph API. An error ends the demo with Meta's message, unless
    `soft`, where it comes back as {"error": ...} for the caller to show."""
    if token:
        params["access_token"] = token
    data = urllib.parse.urlencode(params)
    url = path if path.startswith("http") else f"{GRAPH}{path}"
    if path.startswith("/oauth"):
        # The code exchange carries the app secret: in the body, never the URL.
        req = urllib.request.Request(url, data=data.encode(), method=method)
    else:
        # Everything else goes in the query string, as the production publisher
        # sends it; a body on DELETE is not reliably read by the Graph API.
        req = urllib.request.Request(f"{url}?{data}", data=b"" if method == "POST" else None,
                                     method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if soft:
            return {"error": body[:200]}
        sys.exit(f"\n  API error {e.code} on {method} {path}:\n  {body[:400]}")


def clear() -> None:
    print("\033[2J\033[3J\033[H", end="", flush=True)


def step(n: int, title: str, permission: str) -> None:
    if AUTO:
        clear()  # one screen per step, so nothing scrolls out of the film
    perm = textwrap.fill(permission, 64, initial_indent="  permission: ",
                         subsequent_indent=" " * 14)
    print(f"\n{'=' * 64}\nStep {n}. {title}\n{perm}\n{'=' * 64}")


def pause(msg: str = "Press Enter to continue…", seconds: float = 6) -> None:
    """Wait for Enter, or in auto mode leave the screen up long enough to read."""
    if AUTO:
        time.sleep(seconds)
    else:
        input(f"\n  {msg}")


def confirm(msg: str) -> bool:
    if AUTO:
        return True
    return input(f"\n  {msg} [y/N] ").strip().lower() in ("y", "yes", "т", "так")


def to_clipboard(text: str) -> bool:
    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def from_clipboard() -> str:
    try:
        return subprocess.run(["pbpaste"], capture_output=True, timeout=5).stdout.decode(
            errors="replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def open_in_browser(url: str) -> bool:
    try:
        return subprocess.run(["open", "-a", BROWSER, url], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False


def focus_terminal() -> None:
    """Bring the terminal back in front of the browser."""
    bundle = os.environ.get("__CFBundleIdentifier") or {
        "Apple_Terminal": "com.apple.Terminal", "iTerm.app": "com.googlecode.iterm2",
    }.get(os.environ.get("TERM_PROGRAM", ""))
    if bundle:
        subprocess.run(["open", "-b", bundle], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)


def show_page(url: str, seconds: float = 9) -> None:
    """Auto mode: put a page in front of the viewer, then return to the tool."""
    if url and open_in_browser(url):
        time.sleep(seconds)
        focus_terminal()


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
    """Print a new post's link, then show it in the browser (auto mode) or put
    it on the clipboard for the person to open."""
    print(f"  ✓ {what} published: {link}")
    if AUTO:
        print("  Opening it in the browser…")
        time.sleep(2)
        show_page(link)
        return
    if link and to_clipboard(link):
        print("  ✓ Link copied — paste it into the browser to show it.")
    pause(f"Show the {what.lower()} in the browser, then press Enter…")


def wait_for_code(baseline: str, timeout: float = 900) -> str:
    """The callback page's “Copy code” button puts the code on the clipboard.
    Take it from there, or from the terminal if it is pasted here instead."""
    print("\n  Waiting for the authorization code: log in, grant access, then click\n"
          "  “Copy code” on the page that opens (or paste the code here).")
    deadline = time.time() + timeout
    typing = True
    while time.time() < deadline:
        if typing and select.select([sys.stdin], [], [], 0.5)[0]:
            line = sys.stdin.readline()
            typing = bool(line)  # '' is end-of-input: stop watching the terminal
            if line.strip():
                return line.strip().removesuffix("#_")
        elif not typing:
            time.sleep(0.5)
        clip = from_clipboard().strip().removesuffix("#_")
        if clip != baseline and CODE_RE.fullmatch(clip):
            print("  ✓ Authorization code received from the clipboard.")
            return clip
    sys.exit("\n  No authorization code arrived within 15 minutes.")


def login(app_secret: str) -> str:
    step(1, "Log in with Threads and grant access (OAuth)", ", ".join(SCOPES))
    url = AUTHORIZE + "?" + urllib.parse.urlencode({
        "client_id": APP_ID, "redirect_uri": REDIRECT_URI, "scope": ",".join(SCOPES),
        "response_type": "code", "state": secrets.token_urlsafe(12),
    })
    # The link also replaces the app secret that was just pasted from the clipboard.
    copied = to_clipboard(url)
    opened = False
    if AUTO:
        print("  The Threads login screen opens in a private browser window,\n"
              f"  logged out of Threads.\n\n  {url}")
        time.sleep(5)  # time to read the step before the browser covers it
        opened = open_in_browser(url)
    if opened:
        code = wait_for_code(url)
        focus_terminal()
    else:
        print("  Open the login link in a private browser window, so the demo starts\n"
              "  logged out of Threads.")
        if copied:
            print("  ✓ Link copied — paste it into the private window's address bar.")
        print(f"\n  {url}")
        code = input("\n  Paste the authorization code shown after granting access: ")
    tok = api("POST", "/oauth/access_token", client_id=APP_ID, client_secret=app_secret,
              grant_type="authorization_code", redirect_uri=REDIRECT_URI,
              code=code.strip().removesuffix("#_"))
    print("  ✓ Access token received — the account is connected.")
    if AUTO:
        time.sleep(3)
    return tok["access_token"]


def show_profile(token: str) -> None:
    step(2, "Read the connected account's profile", "threads_basic")
    me = api("GET", "/v1.0/me", token, soft=True,
             fields="id,username,name,threads_biography")
    if "error" in me:
        # Meta refuses any account that is not a tester of the app.
        sys.exit(f"\n  The account that granted access cannot use this app, so it is not\n"
                 f"  @{ACCOUNT}. Nothing was published. Log in as @{ACCOUNT}: the button\n"
                 f"  on the consent screen must name that account.")
    print(f"  Connected account: @{me.get('username')} ({me.get('name', '')})")
    print(f"  Account ID: {me.get('id')}")
    if me.get("threads_biography"):
        print(f"  Bio: {short(me['threads_biography'])}")
    if (me.get("username") or "").lower() != ACCOUNT:
        sys.exit(f"\n  This is not @{ACCOUNT}. Stopping before anything is published.\n"
                 f"  Log in as @{ACCOUNT} in a private browser window and run it again.")
    print("  The app publishes only to accounts our business owns.")
    pause(seconds=6)


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
        for p in posts[:2]:
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
    pause(seconds=14)
    return found


def reply_to_found(token: str, post: dict | None) -> tuple[str, str] | None:
    """Publish the test reply; return its (media id, link)."""
    step(4, "Reply to a post found by search",
         "threads_keyword_search, threads_manage_replies, threads_content_publish")
    if not post:
        print("  Search returned no posts, so there is nothing to reply to.")
        return None
    print(f"  Post: {short(post.get('text'), 76)}\n        {post.get('permalink', '')}")
    print("\n  Reply drafted by the app:\n    "
          + textwrap.fill(REPLY_TEXT, 72, subsequent_indent="    "))
    if not confirm("Publish this reply under the post now?"):
        return None
    if AUTO:
        time.sleep(5)
        print("\n  Publishing the reply…")
    reply_id = publish(token, REPLY_TEXT, reply_to_id=post["id"])
    link = permalink(token, reply_id)
    show_link("Reply", link)
    return reply_id, link


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
    pause(seconds=10)


def publish_own(token: str) -> tuple[str, str] | None:
    """Publish the test post; return its (media id, link)."""
    step(6, "Publish a post to our own account", "threads_content_publish")
    print(f"  Post text:\n    {textwrap.fill(POST_TEXT, 72, subsequent_indent='    ')}")
    if not confirm("Publish this post to the connected account now?"):
        return None
    if AUTO:
        time.sleep(4)
        print("\n  Publishing the post…")
    media_id = publish(token, POST_TEXT)
    link = permalink(token, media_id)
    show_link("Post", link)
    return media_id, link


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
    pause(seconds=10)


def delete_test_posts(token: str, published: list[tuple[str, str, str]]) -> None:
    """Delete the demo's own test items; `published` is emptied as they go."""
    step(8, "Delete our test reply and post", "threads_delete")
    print("  Used to remove our own posts that contain a mistake.")
    if not published:
        print("  Nothing was published, so there is nothing to delete.")
        return
    links = []
    while published:
        label, media_id, link = published[0]
        api("DELETE", f"/v1.0/{media_id}", token)
        published.pop(0)
        links.append(link)
        print(f"  ✓ {label} deleted.")
    if AUTO:
        print("  Opening both links again to show they are gone…")
        time.sleep(3)
        for link in links:
            if link and open_in_browser(link):
                time.sleep(6)
        focus_terminal()
    else:
        pause("Refresh their browser tabs to show they are gone, then press Enter…")


def remove_leftovers(token: str | None, published: list[tuple[str, str, str]]) -> None:
    """The demo stopped early: do not leave its test items on the live account."""
    for label, media_id, link in published:
        res = api("DELETE", f"/v1.0/{media_id}", token, soft=True) if token else {"error": 1}
        print(f"  {label} removed." if "error" not in res
              else f"  {label} is still live — delete it by hand: {link}")


def run_demo(app_secret: str = "") -> None:
    if AUTO:
        clear()
    print("BlackSea — Threads publishing tool\n"
          "Walk-through of every permission requested in app review.\n"
          f"\n  Threads app ID: {APP_ID}")
    if app_secret:
        print("  Threads app secret: entered (hidden)")
        time.sleep(4)
    else:
        app_secret = getpass.getpass("  Threads app secret (hidden): ").strip()
    token = None
    published: list[tuple[str, str, str]] = []
    try:
        token = login(app_secret)
        show_profile(token)
        found = search_niche(token)
        reply = reply_to_found(token, found[0] if found else None)
        if reply:
            published.append(("Test reply", *reply))
        lookup_profiles(token)
        post = publish_own(token)
        if post:
            published.append(("Test post", *post))
        measured = [(f"post of {p.get('timestamp', '')[:10]}", p["id"]) for p in found]
        if post:
            measured.append(("test post (just now)", post[0]))
        if measured:
            show_insights(token, measured)
        delete_test_posts(token, published)
    except BaseException:
        remove_leftovers(token, published)
        raise
    print("\nDone. Every requested permission has been demonstrated.")
    if AUTO:
        time.sleep(5)


# --- recording ---------------------------------------------------------------

def glide(*args: str, timeout: int = 120) -> tuple[bool, dict, str]:
    """Run glide; return (succeeded, its JSON, raw output). The output goes to
    a file, not a pipe: `record start` leaves a recorder running in the
    background, and a pipe it inherited would never reach end-of-file."""
    exe = shutil.which("glide") or str(Path.home() / ".local/bin/glide")
    with tempfile.TemporaryFile() as out:
        try:
            code = subprocess.run([exe, *args], stdout=out, stderr=subprocess.STDOUT,
                                  timeout=timeout).returncode
        except (OSError, subprocess.SubprocessError) as e:
            return False, {}, str(e)
        out.seek(0)
        text = out.read().decode(errors="replace").strip()
    try:
        data = json.loads(text.splitlines()[-1]) if text else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return code == 0 and data.get("ok", True) is not False, data, text


def terminal_script(*lines: str) -> str:
    """Run AppleScript against this terminal's own front window (Terminal.app
    only; anything else, or a failure, returns '')."""
    if os.environ.get("TERM_PROGRAM") != "Apple_Terminal":
        return ""
    script = ['tell application "Terminal"', *lines, "end tell"]
    try:
        r = subprocess.run(["osascript", *[a for s in script for a in ("-e", s)]],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def private_window_in_front() -> bool:
    """Whether the browser's front window is a private one (its title says so)."""
    _, _, text = glide("agent", "--observe", BROWSER, "--limit", "3")
    title = next((line for line in text.splitlines() if line.startswith("Window:")), "")
    return bool(re.search(r"приватн|private", title, re.IGNORECASE))


def fresh_private_window() -> bool:
    """Open a new private window (⌘⇧N) and leave it in front of the browser.

    Links go to the browser's front window, but an existing private window
    cannot be trusted: on 08.10.2026 one opened 13 minutes earlier was still
    "in front", yet the login landed in the personal window and offered the
    personal account (Safari locks private windows left in the background).
    A window opened seconds before the link does take it. The policy page is
    loaded into it straight away, so the film never shows a start page with
    personal favourites."""
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    subprocess.run(["open", "-a", BROWSER], **quiet)
    time.sleep(2)
    glide("agent", "--key", "super+shift+n", "--app", BROWSER, "--no-mark")
    time.sleep(2)
    if not private_window_in_front():
        return False
    subprocess.run(["open", "-a", BROWSER, POLICY_URL], **quiet)
    time.sleep(3)
    return private_window_in_front()


def record_demo() -> None:
    """Film the walk-through with glide and export it as an MP4. Messages for
    the person running it are in Ukrainian; they print outside the filmed part."""
    ok, _, text = glide("permissions", "--check")
    if "PERMISSIONS OK" not in text and "Screen Recording" in text:
        sys.exit("Терміналу потрібен дозвіл на запис екрана.\n"
                 "1. Запусти: glide permissions\n"
                 "2. Системні параметри → Приватність і безпека → Запис екрана: "
                 "увімкни Термінал.\n"
                 "3. Закрий Термінал (⌘Q), відкрий знову і запусти цю команду ще раз.")
    free_gb = shutil.disk_usage(Path.home()).free / 1024 ** 3
    if free_gb < 1.5:  # the raw take plus the export need well under 1 GB
        sys.exit(f"На диску лише {free_gb:.1f} ГБ вільного місця, а запису потрібно "
                 "щонайменше 1,5 ГБ. Звільни місце і запусти ще раз.")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    project = Path.home() / "Movies" / f"blacksea-meta-review-{stamp}.glide"
    video = Path.home() / "Desktop" / f"blacksea-threads-review-{stamp}.mp4"
    project.parent.mkdir(exist_ok=True)

    # A big window and big type, so the reviewer can read the film; put back after.
    old_size = terminal_script("return font size of selected tab of front window")
    was_zoomed = terminal_script("return zoomed of front window")
    terminal_script("set font size of selected tab of front window to 15",
                    "set zoomed of front window to true")

    reason = ""
    recording = False
    try:
        # The secret first, off camera: the private window must be seconds old
        # when the login link opens, not as old as the paste took.
        app_secret = getpass.getpass(
            "Встав секрет застосунку Threads і натисни Enter (символи не показуються): ").strip()
        if not app_secret:
            sys.exit("Секрет порожній.")
        if not fresh_private_window():
            sys.exit(f"Не вдалося відкрити приватне вікно {BROWSER}. "
                     f"Відкрий {BROWSER}, натисни ⌘⇧N і запусти ще раз.")
        focus_terminal()
        ok, _, text = glide("--json", "record", "start", "-o", str(project),
                            "--display", "main", "--fps", "30")
        if not ok:
            sys.exit(f"Запис не почався:\n{text[-600:]}")
        recording = True
        time.sleep(1)
        run_demo(app_secret)
    except SystemExit as e:
        reason = str(e.code or "зупинено").strip()
    except KeyboardInterrupt:
        reason = "перервано (Ctrl+C)"
    finally:
        if recording:
            glide("--json", "record", "stop")
        if old_size:
            terminal_script(f"set font size of selected tab of front window to {old_size}")
        if was_zoomed == "false":
            terminal_script("set zoomed of front window to false")

    if reason:
        draft = f"\nЧорновий запис лишився тут: {project}" if recording else ""
        sys.exit(f"\nЗапис зупинено, відео не зроблено.\nПричина: {reason}{draft}")
    print("\nЗапис завершено. Обробляю відео, це займе кілька хвилин…", flush=True)
    ok, data, text = glide(
        "--json", "render", str(project), "-o", str(video), "--resolution", "1080p",
        "--aspect", "source", "--padding", "0", "--radius", "0", "--shadow", "0",
        "--background", "#000000", "--zoom", "off", "--cursor", "on", "--cursor-style",
        "macos", "--cursor-size", "4", "--click-effect", "on", "--quality", "high",
        "--fps", "30", "--codec", "h264", timeout=3600)
    if not ok:
        sys.exit(f"Відео не зібралося, але запис цілий: {project}\n{text[-600:]}")
    seconds = int(float(data.get("duration") or 0))
    print(f"Готово: {video}  ({seconds // 60}:{seconds % 60:02d})\n"
          "Напиши Claude «готово» — вона перевірить відео перед завантаженням у Meta.")


def main() -> None:
    global AUTO
    ap = argparse.ArgumentParser(description="Threads permissions walk-through for app review")
    ap.add_argument("--auto", action="store_true",
                    help="after the login, run by itself with timed pauses")
    ap.add_argument("--record", action="store_true",
                    help="--auto, filmed with glide and exported as an MP4")
    args = ap.parse_args()
    AUTO = args.auto or args.record
    if args.record:
        record_demo()
    else:
        run_demo()


if __name__ == "__main__":
    main()
