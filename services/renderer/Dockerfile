# Playwright's own image already carries Chromium and every system library it
# needs. Building from python:slim and running `playwright install --with-deps`
# works too, but pulls ~400MB of apt packages at build time and is the step
# that breaks constrained builders — which is the whole reason this service is
# separate from Titan's image in the first place.
#
# The tag MUST match the playwright version in requirements.txt. A mismatch
# between the client library and the bundled browser fails at runtime, not at
# build time, which is the worst place to find it.
FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Most hosts inject their own port. Honour it, default to 8080.
ENV PORT=8080
EXPOSE 8080

# One worker. Each render launches a browser, and several workers on a small
# instance will exhaust memory long before they exhaust CPU.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
