# EPANET-AI: сервис сбора «золотых» ответов от инженеров-гидравликов.
# Образ самодостаточный: EPANET-тулкит приходит внутри пакета wntr (libepanet2*.so),
# внешние сервисы и интернет для работы не нужны.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SERVICE_DATA=/data \
    SERVICE_HOST=0.0.0.0 \
    SERVICE_PORT=8080

WORKDIR /app

# системные зависимости минимальны: wntr-библиотекам нужны только libm/libc
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# данные (БД, загруженные модели, экспорты) живут в томе /data
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "uvicorn", "service.app:app", "--host", "0.0.0.0", "--port", "8080"]
