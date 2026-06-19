# SimPhantom

A Django SaaS platform for buying virtual phone numbers, OTP services, VPN, residential proxies, eSIM, and bulk SMS — powered by the 5sim API, Paystack payments, Bright Data, Twilio, and ESIMCard.

---

## Features

- Virtual number rentals via 5sim API
- OTP receiving for 100+ services and countries
- Residential proxy access via Bright Data
- eSIM provisioning via ESIMCard
- Bulk SMS and phone lookup via Twilio
- Paystack payment integration (card, bank transfer)
- User authentication with JWT + session support
- Rate limiting on sensitive endpoints
- Admin panel for order and user management
- Support ticket system
- Sitemap + robots.txt for SEO
- Dockerized with Nginx reverse proxy and Cloudflare SSL

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 6.0.6, Django REST Framework |
| Auth | JWT (SimpleJWT) + Django sessions |
| Database | PostgreSQL (production), SQLite (development) |
| Payments | Paystack |
| Static files | WhiteNoise + Nginx |
| Containerization | Docker + Docker Compose |
| Reverse proxy | Nginx with Cloudflare Origin Certificate |
| Email | Brevo SMTP relay |

---

## Local Development

### Prerequisites

- Python 3.12+
- pip

### Setup

```bash
# Clone the repo
git clone https://github.com/your-username/simphantom.git
cd simphantom

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Copy and fill in environment variables
cp .env.example .env

# Run migrations
python manage.py migrate

# Start the dev server
python manage.py runserver
```

Visit `http://localhost:8000`

---

## Environment Variables

Copy `.env.example` to `.env` and fill in your values:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Django secret key (50+ random characters) |
| `DJANGO_ENV` | `development` or `production` |
| `ALLOWED_HOSTS` | Comma-separated list of allowed hostnames |
| `DATABASE_URL` | PostgreSQL connection string (production only) |
| `FIVESIM_API_KEY` | 5sim API key for virtual numbers |
| `PAYSTACK_SECRET` | Paystack secret key |
| `PAYSTACK_PUBLIC_KEY` | Paystack public key |
| `BRIGHTDATA_API_KEY` | Bright Data API key for proxies |
| `TWILIO_ACCOUNT_SID` | Twilio SID for SMS |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_FROM_NUMBER` | Twilio sender number |
| `ESIMCARD_API_TOKEN` | ESIMCard API token |
| `EMAIL_HOST_USER` | Brevo SMTP username |
| `EMAIL_HOST_PASSWORD` | Brevo SMTP password |
| `SECURE_SSL_REDIRECT` | `True` once HTTPS is fully configured |

---

## Production Deployment (Docker)

### Prerequisites

- Docker and Docker Compose installed on your server
- Domain pointed to your server via Cloudflare
- Cloudflare SSL mode set to **Full (strict)**

### Steps

1. **Clone the repo on your server**

```bash
git clone https://github.com/your-username/simphantom.git
cd simphantom
```

2. **Place your Cloudflare Origin Certificate**

```
nginx/ssl/cert.pem   ← Origin Certificate
nginx/ssl/key.pem    ← Private Key
```

3. **Create your `.env`**

```ini
DJANGO_ENV=production
SECRET_KEY=your-strong-secret-key
ALLOWED_HOSTS=simphantom.com,www.simphantom.com
DATABASE_URL=postgresql://user:pass@your-db-host/dbname
SECURE_SSL_REDIRECT=False
# ... rest of API keys
```

4. **Build and start**

```bash
docker compose up --build -d
```

On startup the container automatically runs `migrate` and `collectstatic` before Gunicorn starts.

### Services

| Service | Description |
|---|---|
| `web` | Django app running on Gunicorn (port 8000, internal) |
| `nginx` | Reverse proxy on ports 80 and 443, serves static files directly |

---

## Project Structure

```
simphantom/
├── accounts/          # User auth, registration, dashboard
├── orders/            # Order management
├── payments/          # Paystack integration
├── services/          # 5sim, Bright Data, Twilio, ESIMCard
├── support/           # Ticket system
├── main/              # Settings, URLs, sitemaps
├── templates/         # All HTML templates
├── static/            # CSS, JS, images (favicon, logos)
├── nginx/
│   ├── nginx.conf     # Nginx reverse proxy config
│   └── ssl/           # Cloudflare Origin Certificate (not committed)
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh      # migrate → collectstatic → gunicorn
└── requirements.txt
```

---

## License

Private — all rights reserved.
