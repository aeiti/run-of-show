# Development image for the API: Django served as ASGI by runserver (Daphne),
# so HTTP and the live-update WebSockets share one port. The source is
# bind-mounted by docker-compose.yml, so edits reload without a rebuild.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

EXPOSE 8000
# Migrations run on every start, so a pull with new ones just needs a restart.
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py runserver 0.0.0.0:8000"]
