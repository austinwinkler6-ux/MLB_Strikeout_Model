# Real fix (August 2026, per direct user report — the cache-warmer
# reinstalling Chromium and ~110 system packages on EVERY single run,
# taking several real minutes and apparently getting cut off mid-
# install at least once, based on the real logs). Playwright's own
# official image already has Chromium and every real system
# dependency baked in — using it here means the real container never
# needs to install any of that at runtime again, only this one real
# script and its one real dependency.
FROM mcr.microsoft.com/playwright/python:v1.62.0-jammy

WORKDIR /app

COPY warm_cache.py .

CMD ["python", "warm_cache.py"]
