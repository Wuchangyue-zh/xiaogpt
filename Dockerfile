FROM python:3.14-slim
WORKDIR /app
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
RUN python -m venv /app/.venv
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY . .
ENV XIAOGPT_DATA_DIR=/config PYTHONUNBUFFERED=1
VOLUME /config
ENTRYPOINT ["python", "-m", "xiaogpt_voice"]
CMD ["run"]
