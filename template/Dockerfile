# syntax=docker/dockerfile:1.7
#
# One image, one process: the module's backend serves the built UI on port 3001. No Node and no supervisor at run time.
#
#   docker build -t my-module .          a module made from the template: the versions its package-lock.json and
#                                        requirements.lock lock (and requirements.txt pins for the BFF)
#
# Inside the kit's own repository the image is built against the workspace packages instead (CI does this, K1). Give the
# build a context named `kit`: a folder with the packed UI package (npm pack -w packages/ui) and a copy of packages/bff.
#   docker build --build-context kit=kit-context -t template template
FROM scratch AS kit

# ---- the UI, built to static files, from web/package-lock.json (npm ci). Before the kit's first release the lock finds
# @eneo-ai/module-kit in web/vendor/ (see web/vendor/README.md): given a `kit` context, the packed UI package is put there.
FROM node:22-slim AS web
WORKDIR /app/web
COPY web/ ./
RUN --mount=from=kit,target=/kit \
    set -e; \
    pack="$(ls /kit/eneo-ai-module-kit-*.tgz 2>/dev/null | head -n 1 || true)"; \
    if [ -n "$pack" ]; then \
      target="$(node -p "(require('./package-lock.json').packages['node_modules/@eneo-ai/module-kit'].resolved || '').replace(/^file:/, '')")"; \
      case "$target" in vendor/*) mkdir -p vendor && cp "$pack" "$target" ;; esac; \
    fi; \
    npm ci; \
    npm run build

# ---- the backend's packages: what the kit's BFF depends on, locked with hashes (backend/requirements.lock), then the BFF
# itself (git is only here: it is pinned to a commit of the kit until its first release)
FROM python:3.12-slim AS python-packages
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.lock backend/requirements.txt /
RUN pip install --no-cache-dir --prefix=/install --require-hashes --no-deps -r /requirements.lock
RUN --mount=from=kit,target=/kit \
    set -e; \
    if [ -d /kit/bff ]; then \
      cp -r /kit/bff /tmp/bff; \
      pip install --no-cache-dir --prefix=/install --no-deps /tmp/bff; \
    else \
      pip install --no-cache-dir --prefix=/install --no-deps -r /requirements.txt; \
    fi

# ---- what runs
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 STATIC_DIR=/app/web/dist
RUN useradd --system --uid 10001 --no-create-home module
WORKDIR /app
COPY --from=python-packages /install /usr/local
COPY backend/main.py backend/routes.py ./
COPY --from=web /app/web/dist ./web/dist
USER module
EXPOSE 3001
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3001/health', timeout=2)"
CMD ["python", "-c", "from eneo_module_bff import serve; serve('main:build_app', factory=True)"]
