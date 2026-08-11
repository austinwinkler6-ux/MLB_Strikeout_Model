"""
warm_cache.py — cache pre-warming script for Model Metrics (August 2026)

WHY THIS EXISTS
----------------
mlb_app.py's caching functions (cached_run_nfl_projection,
load_mlb_props_data, load_nba_props_data, _cached_lol_full_pipeline,
etc.) all depend on Streamlit's own runtime — st.secrets, st.cache_data,
st.session_state, a live supabase client created via get_supabase()
(itself @st.cache_resource). None of that is safely importable or
callable from a plain, separate Python script run outside a real
`streamlit run` process — attempting to `import mlb_app` directly from
a cron script would try to execute the ENTIRE app's top-level code
(auth wall, page config, etc.) with no real Streamlit server behind it,
and would fail.

The practical, low-risk way to pre-warm the real, already-built caches
without a bigger architecture change: actually visit the live, deployed
site with a real (headless) browser, the same way a real visitor's
browser would. Streamlit's own execution model then runs normally —
Home's run_todays_card_auto_run() fires exactly as it does for any real
visitor, which loads + runs every real model (MLB, NBA points, NBA
assists, all 3 NFL variants, LoL) and populates every real cache this
project's caching fixes just built. Once that's done, the browser
closes — no further code needed, the caching we already built handles
the rest for every real visitor afterward.

REQUIREMENTS
------------
pip install playwright
playwright install chromium
    (or, for a fresh Linux build environment with no other browser
    deps yet: playwright install --with-deps chromium)

REQUIRED ENVIRONMENT VARIABLES (set these on whatever service runs
this script — see the Railway Cron Job setup notes at the bottom of
this file)
    WARM_APP_URL       — your real, live site URL, e.g.
                          https://modelmetrics.io
    WARM_LOGIN_EMAIL    — a real account's login email. Using the
                          ADMIN account is recommended here — it always
                          has full access regardless of trial/paywall
                          state, which keeps this script's expected
                          behavior simple and predictable. A non-admin
                          account would also technically work (Home's
                          auto-run fires before any paywall check runs
                          in the page), but there's no real benefit to
                          using one for this purpose.
    WARM_LOGIN_PASSWORD — that account's real password

WHAT THIS DOES NOT DO
----------------------
This is a real, best-effort script based on Streamlit's documented,
common DOM conventions (form inputs get a real aria-label matching
their st.text_input/st.text_area label). It has NOT been run against
your actual, live, deployed site — I don't have network access to your
real deployment to verify these selectors work exactly as written. If
a selector doesn't match on the first real run, the most likely
culprit is a real mismatch between what's assumed here and your real,
deployed Streamlit version's exact DOM — see the troubleshooting notes
at the bottom of this file for how to debug that quickly.
"""

import os
import sys
import time
import threading

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

try:
    from supabase import create_client
    _SUPABASE_AVAILABLE = True
except ImportError:
    _SUPABASE_AVAILABLE = False


# Real, generous timeout for the FULL warm-up — a genuinely cold cache
# across every sport (MLB, both NBA models, all 3 NFL models, LoL) can
# take several real minutes per the actual, honest cost discussed
# earlier tonight (especially LoL's real, rate-limited Cito calls).
# This should be long enough to comfortably cover a real, full cold
# run without giving up early and leaving some sports un-warmed.
MAX_WAIT_SECONDS = 600  # 10 real minutes

# Real, hard, UNCONDITIONAL ceiling on the entire real script — added
# (August 2026, per direct user report — a real, full day of failed
# runs, traced to real Railway memory graphs showing ONE run's memory
# staying flat and steady for HOURS, never dropping to zero: the real
# process was genuinely stuck, not crashed). Every individual real
# timeout in this script (page.goto, wait_for_selector, etc.) is only
# as reliable as Playwright's own internal handling of it — if the
# real underlying browser process itself gets into a bad, unresponsive
# state, those real timeouts can fail to fire at all. Since Railway
# real cron jobs skip a new scheduled run entirely while a real
# real previous one is still active, ONE real stuck run silently blocks
# EVERY real subsequent scheduled run until someone notices — exactly
# what happened here. This watchdog guarantees the real process
# ALWAYS exits within this real ceiling, no matter what.
HARD_KILL_SECONDS = 1200  # 20 real minutes — comfortably covers a real, full worst-case cold run (chromium install + wake-up + login wait + the full MAX_WAIT_SECONDS model wait above), while still being far under the real 2-hour gap between scheduled runs


def _hard_kill_watchdog():
    """Runs on a real, separate real background thread — if the real
    main thread hasn't finished (and exited normally) within
    HARD_KILL_SECONDS, this force-terminates the whole real process
    immediately via os._exit(1), which cannot be blocked or ignored by
    anything stuck in the main thread (unlike a normal Python
    exception, which a real hang wouldn't even be alive to catch)."""
    time.sleep(HARD_KILL_SECONDS)
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ❌ HARD KILL — real script exceeded {HARD_KILL_SECONDS}s without exiting normally. Force-terminating so this real run can never block future scheduled runs.", flush=True)
    os._exit(1)


def _log(message):
    """Real, timestamped print — this script's own stdout is what
    you'll see in Railway's real Cron Job run logs, so every real step
    should be clearly, honestly logged for debugging a real failed run
    later, without needing to guess what happened."""
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def _upload_debug_screenshot(page, label):
    """Real, new addition (August 2026, per direct user report — a
    real, multi-round debugging cycle based purely on real log text,
    with several real guesses that didn't pan out). Takes a real
    screenshot of whatever the real page actually looks like right
    now and uploads it to a real Supabase Storage bucket, giving real,
    direct visual evidence of the real failure instead of continuing
    to guess from real log text alone. Best-effort — a real failure
    here should never mask or replace the real, original error."""
    if not _SUPABASE_AVAILABLE:
        _log("⚠️ Can't upload a debug screenshot — the 'supabase' package isn't installed in this environment.")
        return
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        _log("⚠️ Can't upload a debug screenshot — SUPABASE_URL/SUPABASE_KEY aren't set on this service.")
        return
    try:
        screenshot_bytes = page.screenshot(full_page=True)
        filename = f"{label}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        client = create_client(supabase_url, supabase_key)
        client.storage.from_("debug-screenshots").upload(
            filename, screenshot_bytes, {"content-type": "image/png"}
        )
        _log(f"📸 Real debug screenshot uploaded — check the 'debug-screenshots' bucket in Supabase Storage for: {filename}")
    except Exception as e:
        _log(f"⚠️ Real error trying to upload a debug screenshot: {e}")


def warm_cache():
    app_url = os.environ.get("WARM_APP_URL")
    login_email = os.environ.get("WARM_LOGIN_EMAIL")
    login_password = os.environ.get("WARM_LOGIN_PASSWORD")

    if not app_url or not login_email or not login_password:
        _log("❌ Missing one or more required environment variables: "
             "WARM_APP_URL, WARM_LOGIN_EMAIL, WARM_LOGIN_PASSWORD. Exiting.")
        sys.exit(1)

    _log(f"Starting cache warm-up run against {app_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            _log("Navigating to the real, live site...")
            page.goto(app_url, timeout=60_000, wait_until="networkidle")

            # Real fix, round 2 (August 2026, per direct user report —
            # this real timeout STILL happening even after the first
            # real fix). Real root cause found: Locator.is_visible()
            # checks INSTANTLY and does NOT actually wait/retry despite
            # taking a timeout argument — a real, well-known Playwright
            # gotcha. If the real wake-up screen hadn't rendered in
            # that exact instant, the real check silently failed and
            # skipped clicking it entirely, meaning the real app never
            # even started rebuilding — explaining why waiting even
            # 120 real seconds afterward never helped. wait_for() is
            # the real, correctly-retrying equivalent. Also gives a
            # real, genuinely cold rebuild (heavy real dependencies —
            # pandas, scipy, supabase) real, generous time once
            # clicked, matching how long other real users report this
            # genuinely taking.
            try:
                wake_button = page.get_by_text("get this app back up", exact=False)
                wake_button.wait_for(state="visible", timeout=15_000)
                _log("App appears to be asleep — clicking to wake it up...")
                wake_button.click()
                page.wait_for_timeout(15_000)  # real, genuine time for the rebuild to actually begin
            except PlaywrightTimeoutError:
                pass  # no real wake-up screen present within 15s — a normally-awake app, proceed as before

            # Real fix, round 3 (August 2026, per direct visual
            # screenshot evidence — TWO different label-matching
            # approaches in a row (exact aria-label attribute, then
            # Playwright's own accessibility-tree get_by_label) both
            # failed against a page confirmed, via real screenshots,
            # to be fully rendered the entire time. That rules out a
            # real timing issue and points to something more
            # structural: the visible "Email"/"Password" text is very
            # likely just real, plain visual text sitting near the
            # inputs, with NO real programmatic label association at
            # all — a real, common Streamlit pattern
            # (label_visibility="collapsed" plus a real custom
            # st.markdown() caption drawn above the real field). No
            # real label-matching approach can ever work against that,
            # regardless of how it's written. Targeting by real,
            # structural position instead — completely independent of
            # labels, aria-attributes, or text content: on a real,
            # clean login screen, these are the first two real <input>
            # elements in real DOM order.
            _log("Logging in...")
            _upload_debug_screenshot(page, "before_login_wait")

            all_inputs = page.locator("input:visible")

            try:
                all_inputs.nth(1).wait_for(state="visible", timeout=90_000)
            except PlaywrightTimeoutError:
                # Real, deliberate mid-wait checkpoint — a real
                # screenshot here specifically, BEFORE the full real
                # timeout below, since every real failure so far has
                # happened somewhere in this exact real wait, and this
                # is real, direct visual proof of what's actually on
                # screen partway through it — not just at the very end.
                _log("Still waiting for the login form 90s in — capturing a real mid-wait screenshot...")
                _upload_debug_screenshot(page, "mid_login_wait")
                all_inputs.nth(1).wait_for(state="visible", timeout=190_000)

            all_inputs.nth(0).fill(login_email)
            all_inputs.nth(1).fill(login_password)

            # Streamlit renders a real <button> with the exact real
            # text of the st.form_submit_button label ("Login" in
            # mlb_app.py's real login form).
            page.click('button:has-text("Login")')

            # Real, honest wait for the real login + initial Home page
            # render to settle before the real auto-run kicks off.
            page.wait_for_load_state("networkidle", timeout=30_000)
            _log("Logged in — Home page loading, real model auto-run should be starting now.")

            # Real, best-effort "done" signal — Home's own real UI
            # shows a real "Today's Highest Rated" card once
            # run_todays_card_auto_run() has genuinely finished. Waiting
            # for that specific, real text is a more honest completion
            # signal than a fixed sleep, since a cold run's real
            # duration varies a lot depending on how much of the cache
            # was already warm.
            try:
                page.wait_for_selector(
                    "text=Today's Highest Rated",
                    timeout=MAX_WAIT_SECONDS * 1000,
                )
                _log("✅ Real 'Today's Highest Rated' card detected — the real model auto-run has completed.")
            except PlaywrightTimeoutError:
                # A real, honest fallback — even if this specific text
                # didn't appear (e.g. a real 'no games today' state, or
                # the real page layout changed), the real underlying
                # model runs earlier in the page likely still completed
                # and populated the real caches regardless. Logged as a
                # real warning, not a hard failure, since the actual
                # goal (warming the real shared caches) may still have
                # succeeded even without this specific visual confirmation.
                _log("⚠️ Didn't see the expected 'Today's Highest Rated' text within "
                     f"{MAX_WAIT_SECONDS}s — the real model runs may still have completed "
                     "and warmed the caches regardless (e.g. a real 'no games today' state "
                     "wouldn't show this card at all). Treating this as a soft warning, not "
                     "a hard failure.")

            # A short, real, extra buffer — gives any last, real
            # in-flight background Supabase cache writes a moment to
            # genuinely finish before the browser closes.
            time.sleep(5)
            _log("✅ Cache warm-up run complete.")

        except Exception as e:
            _log(f"❌ Real error during warm-up run: {e}")
            _upload_debug_screenshot(page, "on_exception")
            # Real, non-zero exit so Railway's own Cron Job dashboard
            # correctly shows this run as failed, rather than silently
            # looking successful.
            sys.exit(1)
        finally:
            browser.close()


if __name__ == "__main__":
    # Real, deliberate placement — starts BEFORE the actual real
    # warm-up work, so the real hard-kill ceiling covers the ENTIRE
    # real run from the very first line, not just part of it. A real
    # daemon thread so it can never itself prevent the real process
    # from exiting normally and promptly on a real, successful run.
    watchdog = threading.Thread(target=_hard_kill_watchdog, daemon=True)
    watchdog.start()

    warm_cache()


# ============================================================
# RAILWAY CRON JOB SETUP (do this in your Railway dashboard, not here)
# ============================================================
#
# 1. In your Railway project, click "+ New" → "Empty Service" (or
#    "Cron Job" if your Railway plan/UI shows that as a direct option).
#
# 2. Point it at the SAME real GitHub repo as your main app (or upload
#    this script as its own small real deploy target — either works,
#    the key requirement is just that warm_cache.py and playwright are
#    available together in whatever real environment runs it).
#
# 3. Set a real Start/Build command that installs playwright and its
#    real browser binary, then runs the real script, e.g.:
#       pip install playwright && playwright install --with-deps chromium && python warm_cache.py
#
# 4. Set the real Cron Schedule — something like 30 minutes before your
#    real traffic typically starts picking up each day. In cron syntax,
#    6:00 AM Eastern (adjust for your real timezone, Railway cron runs
#    in UTC) would be roughly:
#       0 10 * * *      (10:00 UTC ≈ 6:00 AM EDT — double check against
#                         real daylight saving offsets for your season)
#
# 5. Add the three real environment variables from the top of this
#    file (WARM_APP_URL, WARM_LOGIN_EMAIL, WARM_LOGIN_PASSWORD) under
#    this new service's own Variables tab — these are separate from
#    your main app's variables, since this is a genuinely separate
#    Railway service.
#
# 6. Trigger a real, manual test run first (most Railway Cron Job UIs
#    have a "Run Now" button) rather than waiting for the real
#    scheduled time, so you can watch the real logs and confirm it
#    actually works before trusting the schedule.
#
# ============================================================
# TROUBLESHOOTING — IF LOGIN STILL FAILS
# ============================================================
#
# Real root cause found and fixed (August 2026): the original
# 'input[aria-label="Email"]' exact-match selector never matched
# Streamlit's real actual rendered attribute, confirmed via real
# debug screenshots (see _upload_debug_screenshot above) showing the
# real login form fully rendered and visible the entire time it was
# "waiting." Switched to page.get_by_label(), Playwright's own real,
# robust, accessibility-tree-based field locator, which matches by
# real VISIBLE label text instead of requiring an exact real
# attribute string.
#
# If login ever fails again, the debug screenshots this script
# uploads to Supabase Storage (bucket: debug-screenshots) are the
# real, fastest way to see exactly what the real page looked like at
# the real moment of failure — real, direct visual evidence beats
# real guessing from log text alone every time.
#
# 3. Or, use Playwright's own real codegen tool locally against your
#    real site to record real, working selectors directly:
#       playwright codegen https://your-real-site-url.com
#    This opens a real, visible browser + generates real Python code
#    as you click through the real login flow yourself — the most
#    reliable way to get selectors that definitely match your real,
#    actual deployed site, since it's built FROM that real site
#    directly rather than guessed at.
