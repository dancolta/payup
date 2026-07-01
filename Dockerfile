# PayUp Slack bot. Socket Mode means no inbound ports: the container just needs
# to stay alive and reach out to Slack, QuickBooks, and Gmail.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/engine

WORKDIR /app

# Install the bot runtime first for better layer caching.
COPY pyproject.toml requirements.txt README.md ./
RUN pip install --no-cache-dir -e '.[bot]'

# App code (no secrets: those come from the host env / fly secrets).
COPY engine/ engine/
COPY bot/ bot/
COPY config/ config/
COPY fixtures-sandbox/ fixtures-sandbox/

# Drop privileges.
RUN useradd --create-home --uid 10001 payup && chown -R payup /app
USER payup

# Dry-run by default. Set PAYUP_LIVE=1 (and provide secrets) to send for real.
ENV PAYUP_LIVE=0

CMD ["python", "-m", "bot.app"]
