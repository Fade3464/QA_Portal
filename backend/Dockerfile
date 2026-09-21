FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/staticfiles /app/media /media /recordings && chown -R app:app /app /media /recordings

USER app

RUN DJANGO_DEBUG=true python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["sh", "/app/entrypoint.sh"]
