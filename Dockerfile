FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir fastapi uvicorn[standard] pydantic pydantic-settings

COPY apps ./apps
COPY packages ./packages
COPY infrastructure ./infrastructure

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "apps.agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
