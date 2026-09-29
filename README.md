# FundiFinder backend

Django + DRF + GeoDjango (PostGIS) API for FundiFinder: clients in Tanzania find and book
identity-verified local service providers ("fundis").

## Quick start

### Option A: Docker (recommended, especially on Windows)

Needs only [Git](https://git-scm.com/download/win) and
[Docker Desktop](https://www.docker.com/products/docker-desktop/) (GDAL, GEOS and PostGIS come inside
the containers). In PowerShell:

```powershell
cd "C:\Users\official pc\PROJECTS"
git clone https://github.com/shilla255/fundifinder-backend.git
cd fundifinder-backend
git checkout claude/laughing-faraday-jvoj41     # until this branch is merged into main
Copy-Item .env.example .env
docker compose up --build                        # first build takes a few minutes
```

In a second terminal:

```powershell
docker compose exec web python manage.py seed_demo          # categories + verified demo fundis
docker compose exec web python manage.py createsuperuser    # your admin login
docker compose exec web python manage.py test apps          # run the test suite
```

Later: `git pull` to update, `docker compose up` to start, `docker compose down` to stop.

### Option B: without Docker

Requires Python 3.11+, PostgreSQL with PostGIS, and GDAL/GEOS (on Windows via
[OSGeo4W](https://trac.osgeo.org/osgeo4w/); then set `GDAL_LIBRARY_PATH` / `GEOS_LIBRARY_PATH` in `.env`).

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_demo
python manage.py createsuperuser
python manage.py runserver
```

### Try the full workflow

1. **Browse the API** at http://localhost:8000/api/v1/ (the browsable API). Click *Log in* (top right) and
   use a demo account, password `demo-pass-123`:
   - `client@demo.fundifinder`: a client
   - `juma@demo.fundifinder`, `neema@demo.fundifinder`, `baraka@demo.fundifinder`: verified fundis
2. **Search**: http://localhost:8000/api/v1/fundis/search/?lat=-6.7711&lng=39.2489&radius_km=5&category=electrical
3. **Book** as the client: POST to `/api/v1/bookings/` with
   `{"fundi_id": "...", "category": "electrical", "description": "...", "latitude": -6.7711, "longitude": 39.2489, "job_address": "Mwenge"}`
4. Log out, log in as that fundi, open `/api/v1/bookings/?as=fundi`, then POST to
   `/api/v1/bookings/<id>/accept/`, `/start/`, `/complete/`.
5. As the client, POST `{"rating": 5}` to `/api/v1/bookings/<id>/review/`. Check `/api/v1/notifications/`.
6. **Phone sign-up**: POST a phone number to `/api/v1/auth/otp/request/`. With the console SMS backend
   the 6-digit code is printed in the server terminal ("SMS to +255...").
7. **Identity review**: submit `/api/v1/verification/` as a new user, then approve it at
   http://localhost:8000/admin/ → *Identity verifications*.

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
| POST | `/api/v1/auth/firebase/` | `{id_token, purpose?}`: phone sign-in via Firebase Auth (web + mobile). `purpose=verify_phone` attaches the number to the signed-in user |
| POST | `/api/v1/auth/otp/request/`, `/auth/otp/verify/` | Phone login / phone verification (needs `PHONE_OTP_ENABLED`) |
| POST | `/api/v1/auth/token/refresh/`, `/auth/logout/` | JWT refresh / blacklist refresh token |
| POST | `/api/v1/auth/dev-login/` | **DEBUG only**: email + password → JWT, for `seed_demo` accounts |
| GET/PATCH | `/api/v1/me/` | Own account |
| GET | `/api/v1/categories/` | Public |
| GET | `/api/v1/fundis/search/?lat=&lng=&radius_km=&category=` | Public, nearest first |
| GET | `/api/v1/fundis/{id}/` | Public fundi profile (includes `approx_location`, rounded to ~1 km) |
| GET | `/api/v1/fundis/{id}/reviews/` | Public reviews (reviewer first name only) |
| POST/GET/PATCH | `/api/v1/fundi/profile/` | Become a fundi / manage own profile (`latitude`, `longitude`) |
| POST | `/api/v1/fundi/profile/activate/`, `/pause/` | Publish or hide own profile |
| CRUD | `/api/v1/fundi/services/` | Own services (max `FUNDI_MAX_SERVICES`) |
| GET/POST | `/api/v1/verification/` | Own identity status / submit documents |
| GET/POST | `/api/v1/bookings/` | `?as=client` (default) or `?as=fundi`, `?status=` |
| POST | `/api/v1/bookings/{id}/accept\|decline\|start\|complete\|confirm\|cancel\|dispute/` | `note` required for cancel/dispute |
| POST | `/api/v1/bookings/{id}/review/` | Client, after completion |
| GET/POST | `/api/v1/notifications/`, `/{id}/read/`, `/read-all/` | In-app notifications |

## Google Cloud setup

**Google Sign-In** (project `fundi-finder-510106`, web client "Django Backend"):

- The backend only needs the **client ID** (`GOOGLE_OAUTH_CLIENT_IDS`). It verifies ID tokens against
  Google's public keys; the client secret is not used and must not be committed.
- Mobile apps: create an *Android* client (package name + SHA-1) and an *iOS* client in the same project,
  but request the ID token with the **web client ID as `serverClientId`** (Android Credential Manager /
  `google_sign_in` on Flutter). The token's audience is then the web client ID, which the backend already
  accepts. If a token carries a different audience, add that client ID to the list.
- While the OAuth consent screen is in *Testing*, only listed test users can sign in
  (*Google Auth Platform → Audience*). Publish the app before launch.

Flow: app signs in with Google → sends the **ID token** to `POST /api/v1/auth/google/` → gets FundiFinder
JWTs back.

Suggested production stack on GCP: Cloud Run (app) + Cloud SQL for PostgreSQL with PostGIS + a private
Cloud Storage bucket for ID documents (`django-storages`, signed URLs) + Cloud Scheduler for
`process_bookings` + Firebase Cloud Messaging for push notifications.

## Not built yet

- **Phone sign-in** already works through Firebase Authentication (Firebase sends the SMS): set
  `FIREBASE_PROJECT_ID`. The app/website verifies the number with the Firebase SDK and posts the Firebase
  ID token to `/api/v1/auth/firebase/`.
- **SMS for notifications:** implement a `BaseSMSBackend` subclass in `apps/notifications/sms.py` (Beem, NextSMS, ...) and set
  `SMS_BACKEND`; then set `PHONE_OTP_ENABLED=true`.
- **NIDA API:** see *Identity verification* above.
- Push notifications (FCM), account deletion/anonymisation, trade licences/credentials per service,
  payment gateway (mobile money).
