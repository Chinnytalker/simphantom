#!/bin/sh
set -e

echo "==> Running database migrations..."
python manage.py migrate --noinput

echo "==> Configuring site domain..."
python manage.py shell -c "
from django.contrib.sites.models import Site
import os
domain = os.environ.get('ALLOWED_HOSTS', 'simphantom.com').split(',')[0]
Site.objects.update_or_create(id=1, defaults={'domain': domain, 'name': 'SimPhantom'})
print('Site domain set to:', domain)
"

echo "==> Collecting static files..."
python manage.py collectstatic --noinput

echo "==> Starting Gunicorn..."
exec gunicorn main.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
