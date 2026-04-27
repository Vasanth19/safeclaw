# SafeClaw — Onboarding Webapp
#
# Customer-facing setup wizard. Lives at port 80/443 of the customer's VPS
# (via Caddy reverse proxy) and provisions the SafeClaw stack live in the
# customer's browser with SSE progress streaming.
#
# This image must be light: only Flask + gunicorn + requests + the docker
# CLI (so the webapp can drive `docker compose` against the host socket).

FROM python:3.12-slim

# docker CLI + compose plugin (so the webapp can run `docker compose ...`),
# plus git for the bootstrap-brain step (clones the Evolving Brain Template).
# We install Docker's official packages from download.docker.com because the
# Debian-shipped docker.io is missing the compose plugin on some releases.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && . /etc/os-release \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        docker-ce-cli \
        docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py
COPY lib /app/lib
COPY templates /app/templates
COPY static /app/static

ENV PYTHONUNBUFFERED=1 \
    SAFECLAW_INSTALL_DIR=/safeclaw \
    PORT=8080

EXPOSE 8080

# 2 workers (one for the form/API, one for SSE), 4 threads each.
# Long timeouts because provision can take 5+ minutes.
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "600", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]
