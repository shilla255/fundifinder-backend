# FundiFinder backend

Django + DRF + GeoDjango (PostGIS) API for FundiFinder: clients in Tanzania find and book
identity-verified local service providers ("fundis").

## Quick start

Requirements: Python 3.11+, GDAL/GEOS (GeoDjango), Docker (for PostGIS) or a local PostGIS.

```bash
docker compose up -d db                      # PostGIS on localhost:5432
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                         # then edit
python manage.py migrate
python manage.py seed_categories
python manage.py createsuperuser             # email + password, for /admin
python manage.py runserver
python manage.py test apps
```

GDAL on Ubuntu: `apt install gdal-bin`. On Windows/macOS set `GDAL_LIBRARY_PATH` /
`GEOS_LIBRARY_PATH` in `.env` if Django can't find them.

## Apps

| App | Responsibility |
| --- | --- |
| `core` | UUID base model, phone normalisation (E.164), encryption helpers, test helpers |
| `accounts` | `User` (one account per person), Google Sign-In, phone OTP (off until an SMS gateway exists), JWT |
| `catalog` | `ServiceCategory` (two levels, English + Kiswahili names) |
| `fundis` | `FundiProfile` (optional provider side of a user), `FundiService` (categories + pricing), geo search |
| `verification` | `IdentityVerification` (NIDA photo + selfie submissions, manual admin review), audit log |
| `bookings` | `Booking` state machine, `BookingEvent` history, `Review` |
| `notifications` | In-app `Notification`, SMS backend interface (console for now), Swahili/English texts |

## Key rules

- **No role field.** A user is a fundi if they have a `FundiProfile`. The same person can be a
  client on one booking and the fundi on another; booking yourself is blocked.
- **Two separate states.** `User.identity_status` (unverified → pending → verified / rejected /
  reverification_required / revoked) is about *who you are*. `FundiProfile.status` (draft / active /
  paused / suspended / banned) is about *conduct and availability*.
- **Search visibility** = identity verified + profile active + available + account active. Defined once in
  `FundiProfileQuerySet.discoverable()`.
- **Search radius.** A fundi shows up only if the client is inside the fundi's service radius *and* the
  fundi is inside the client's search radius. Clients see distance, never the fundi's coordinates.
- **Contact privacy.** Phone numbers and exact job coordinates are shared only after the fundi accepts.
- **NIDA data.** Numbers are encrypted (Fernet) with an HMAC hash for duplicate detection. One NIDA
  number can be approved on only one account (DB constraint). ID photos live in private storage and are
  viewable only by staff through the admin.

## Identity verification (manual for now)

1. User `POST /api/v1/verification/` (multipart): `nida_number`, `full_name`, `date_of_birth`,
   `id_front_image`, optional `id_back_image`, `selfie_image`.
2. Staff open **Admin → Identity verifications**, filter by *Pending*, compare the photos and details
   (the page flags duplicate NIDA numbers and whether the birth date matches the NIDA number), then click
   **Approve identity** or set a rejection reason and click **Reject**.
3. The user is notified; a rejected user can resubmit. Every change is logged in `VerificationEvent`.

When NIDA API access is available, add an automated check that sets `method="nida_api"` and calls the
same `approve` / `reject` services.

## Booking lifecycle

```
requested ─accept→ accepted ─start→ in_progress ─complete→ completed ─confirm/review→ closed
    ├─decline→ declined                 └─dispute→ disputed ←dispute─┘
    ├─expire→ expired (no answer within BOOKING_RESPONSE_MINUTES)
    └─cancel→ cancelled ←cancel─ accepted
```

Run `python manage.py process_bookings` every few minutes (cron, or Cloud Scheduler in production) to
expire unanswered requests and auto-close completed jobs after `BOOKING_AUTO_CLOSE_HOURS`.

## API (v1)

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/v1/auth/google/` | `{id_token}` from Google Sign-In → JWT pair + user |
| POST | `/api/v1/auth/otp/request/`, `/auth/otp/verify/` | Phone login / phone verification (needs `PHONE_OTP_ENABLED`) |
| POST | `/api/v1/auth/token/refresh/`, `/auth/logout/` | JWT refresh / blacklist refresh token |
| GET/PATCH | `/api/v1/me/` | Own account |
| GET | `/api/v1/categories/` | Public |
| GET | `/api/v1/fundis/search/?lat=&lng=&radius_km=&category=` | Public, nearest first |
| GET | `/api/v1/fundis/{id}/` | Public fundi profile |
| POST/GET/PATCH | `/api/v1/fundi/profile/` | Become a fundi / manage own profile (`latitude`, `longitude`) |
| POST | `/api/v1/fundi/profile/activate/`, `/pause/` | Publish or hide own profile |
| CRUD | `/api/v1/fundi/services/` | Own services (max `FUNDI_MAX_SERVICES`) |
| GET/POST | `/api/v1/verification/` | Own identity status / submit documents |
| GET/POST | `/api/v1/bookings/` | `?as=client` (default) or `?as=fundi`, `?status=` |
| POST | `/api/v1/bookings/{id}/accept\|decline\|start\|complete\|confirm\|cancel\|dispute/` | `note` required for cancel/dispute |
| POST | `/api/v1/bookings/{id}/review/` | Client, after completion |
| GET/POST | `/api/v1/notifications/`, `/{id}/read/`, `/read-all/` | In-app notifications |

## Google Cloud setup

**Google Sign-In:** in Google Cloud Console → *APIs & Services → Credentials*, create OAuth client IDs
(Web, and Android/iOS for the mobile apps) and put them comma-separated in `GOOGLE_OAUTH_CLIENT_IDS`.
The app signs in with Google, sends the resulting **ID token** to `/api/v1/auth/google/`, and the backend
verifies it.

Suggested production stack on GCP: Cloud Run (app) + Cloud SQL for PostgreSQL with PostGIS + a private
Cloud Storage bucket for ID documents (`django-storages`, signed URLs) + Cloud Scheduler for
`process_bookings` + Firebase Cloud Messaging for push notifications.

## Not built yet

- **SMS:** implement a `BaseSMSBackend` subclass in `apps/notifications/sms.py` (Beem, NextSMS, ...) and set
  `SMS_BACKEND`; then set `PHONE_OTP_ENABLED=true`.
- **NIDA API:** see *Identity verification* above.
- Push notifications (FCM), account deletion/anonymisation, trade licences/credentials per service,
  payment gateway (mobile money).
