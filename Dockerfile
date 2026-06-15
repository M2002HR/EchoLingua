FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY echolingua ./echolingua
COPY config ./config
COPY data ./data

RUN pip install --no-cache-dir -e ".[dev,edge]"

CMD ["python", "-m", "echolingua.cli", "--help"]
