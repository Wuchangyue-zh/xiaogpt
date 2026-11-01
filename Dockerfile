FROM python:3.14

WORKDIR /app
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
RUN python -m venv /app/.venv
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY . .

ENV HOME=/config \
    XIAOGPT_CONFIG_DIR=/config \
    XIAOGPT_MI_TOKEN_PATH=/config/.mi.token \
    XIAOGPT_SMART_ROOT=/config/smart_voice \
    PYTHONUNBUFFERED=1
VOLUME /config
ENTRYPOINT ["python", "runtime.py"]
CMD ["--config", "/config/config.json"]
