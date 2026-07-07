# Multi-language image: Node.js server + Python helper for DK API.
# The Python helper uses curl_cffi for Chrome TLS impersonation to bypass
# DraftKings' Akamai bot protection.

FROM node:20-slim

# Install Python + build tools (needed for curl_cffi C extension)
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 \
      python3-pip \
      python3-venv \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps (into a venv to avoid system-Python conflicts on Debian)
COPY requirements.txt ./
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Put venv on PATH so `python3` in server.js resolves to the venv Python
ENV PATH="/opt/venv/bin:${PATH}"

# Chromium for the DK_COOKIE_BROWSER cookie minter. Only exercised when that
# flag is set; the browser + its apt runtime deps are installed here so the
# minter can launch it. Playwright finds it automatically via
# PLAYWRIGHT_BROWSERS_PATH, so DK_CHROMIUM_PATH does not need to be set.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN /opt/venv/bin/playwright install --with-deps chromium

# Node deps
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

# App source
COPY . .

EXPOSE 3000
CMD ["node", "server.js"]
