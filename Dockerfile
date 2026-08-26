FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

RUN addgroup --system --gid 10001 webmonitor \
    && adduser --system --uid 10001 --ingroup webmonitor --home /nonexistent webmonitor \
    && mkdir -p /data /config \
    && chown -R webmonitor:webmonitor /data /config /app

COPY --chown=webmonitor:webmonitor main.py web_monitor.py notifications.py health.py ./

USER webmonitor

VOLUME ["/data"]

ENTRYPOINT ["python", "main.py"]
CMD ["--config", "/config/config.json"]
