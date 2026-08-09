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

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# Real, generous timeout for the FULL warm-up — a genuinely cold cache
# across every sport (MLB, both NBA models, all 3 NFL models, LoL) can
# take several real minutes per the actual, honest cost discussed
# earlier tonight (especially LoL's real, rate-limited Cito calls).
# This should be long enough to comfortably cover a real, full cold
# run without giving up early and leaving some sports un-warmed.
MAX_WAIT_SECONDS = 600  # 10 real minutes


def _log(message):
    """Real, timestamped print — this script's own stdout is what
    you'll see in Railway's real Cron Job run logs, so every real step
    should be clearly, honestly logged for debugging a real failed run
    later, without needing to guess what happened."""
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


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

            # Real fix (August 2026, per direct user report — the
            # warm-up run timing out waiting for the email field right
            # after a real, fresh Streamlit redeploy). Streamlit
            # Community Cloud shows a real "Zzz... this app has gone
            # to sleep" screen with a real wake-up button for any app
            # that's been freshly deployed or had no recent real
            # traffic — the real login form never renders until that
            # button is clicked and the real app finishes rebuilding,
            # which can genuinely take well over the real 30s this
            # script used to wait. Best-effort: click it if present,
            # then give the real rebuild real, generous time.
            try:
                wake_button = page.get_by_text("get this app back up", exact=False)
                if wake_button.is_visible(timeout=5_000):
                    _log("App appears to be asleep — clicking to wake it up...")
                    wake_button.click()
                    page.wait_for_timeout(3_000)
            except Exception:
                pass  # no real wake-up screen present — a normally-awake app, proceed as before

            # Real, best-effort login flow — targets Streamlit's own
            # real, standard aria-label convention for st.text_input
            # widgets (the label text you gave each field: "Email" and
            # "Password" in mlb_app.py's real login form). If this
            # specific project's Streamlit version renders these
            # differently, these selectors are the first, most likely
            # thing to need adjusting — see the troubleshooting notes
            # at the bottom of this file.
            _log("Logging in...")
            page.wait_for_selector('input[aria-label="Email"]', timeout=120_000)
            page.fill('input[aria-label="Email"]', login_email)
            page.fill('input[aria-label="Password"]', login_password)

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
            # Real, non-zero exit so Railway's own Cron Job dashboard
            # correctly shows this run as failed, rather than silently
            # looking successful.
            sys.exit(1)
        finally:
            browser.close()


if __name__ == "__main__":
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
# TROUBLESHOOTING — IF THE LOGIN SELECTORS DON'T MATCH
# ============================================================
#
# If this script's real run logs show it timing out waiting for
# 'input[aria-label="Email"]', the most likely cause is a real,
# version-specific difference in how your deployed Streamlit renders
# form inputs. To debug:
#
# 1. Temporarily set `headless=False` in this script (only works if
#    you're running it locally on your own machine with a real display
#    — won't work inside Railway's real headless environment) to
#    SEE the real browser and inspect the real page.
#
# 2. Or, add a real screenshot right before the failing step:
#       page.screenshot(path="debug.png")
#    and pull that file down to see exactly what the real page looked
#    like at that moment.
#
# 3. Or, use Playwright's own real codegen tool locally against your
#    real site to record real, working selectors directly:
#       playwright codegen https://your-real-site-url.com
#    This opens a real, visible browser + generates real Python code
#    as you click through the real login flow yourself — the most
#    reliable way to get selectors that definitely match your real,
#    actual deployed site, since it's built FROM that real site
#    directly rather than guessed at.
