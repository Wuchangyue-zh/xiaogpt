FROM python:3.14

WORKDIR /app
COPY pyproject.toml pdm.lock README.md ./
RUN pip install --no-cache-dir pdm==2.29.2 && \
    pdm install --prod --no-self --frozen-lockfile
COPY . .

ENV HOME=/config \
    XIAOGPT_CONFIG_DIR=/config \
    XIAOGPT_MI_TOKEN_PATH=/config/.mi.token \
    XIAOGPT_SMART_ROOT=/config/smart_voice \
    PYTHONUNBUFFERED=1
VOLUME /config
ENTRYPOINT ["pdm", "run", "python", "runtime.py"]
CMD ["--config", "/config/config.json"]
