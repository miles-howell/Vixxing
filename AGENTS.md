# Agent notes: Vixxing

Read this before touching code. It exists because agents keep re-deriving
(and getting wrong) the same handful of facts about this project.

## What this is

A small internal Django app ("Vixxing" / "TOTP") that gives IT help-desk
agents a way to verify a caller's identity live on the phone using TOTP
codes, before resetting a password or MFA. See `README.md` for the full
product pitch. This file is about the codebase, not the pitch.

## The two facts agents get wrong most often

1. **This project runs Django 6.1**, pinned in `requirements.txt`
   (`Django==6.1`). It is not Django 4 or 5. Django 6 changed and removed
   things relative to older versions you may have been trained on — check
   the Django 6.1 docs (linked in comments throughout `settings.py`)
   before assuming an older-Django pattern still applies. Don't "fix"
   settings or code to match Django 4/5 idioms.

2. **`MAILERS` in `TOTP/TOTP/settings.py` is correct and intentional.**
   ```python
   MAILERS = {
       'default': {
           'BACKEND': 'msgraphbackend.MSGraphBackend',
       },
   }
   ```
   `MAILERS` is a real Django 6.0+ setting (see
   https://docs.djangoproject.com/en/6.1/topics/email/) that replaces the
   old single-backend `EMAIL_BACKEND` model with a `DATABASES`/`CACHES`-style
   dict of named mailers. This is **not** a typo for `EMAIL_BACKEND`, not a
   custom project setting, and not dead code. Do not "correct" it to
   `EMAIL_BACKEND = '...'`, and do not add an `EMAIL_BACKEND` setting
   alongside it — that would just create a second, conflicting way to
   configure mail. The `'default'` mailer's `BACKEND` points at
   `msgraphbackend.MSGraphBackend` from the `django-msgraphbackend` package,
   which sends mail through the Microsoft Graph API using
   `MSGRAPH_TENANT_ID` / `MSGRAPH_CLIENT_ID` / `MSGRAPH_CLIENT_SECRET` /
   `MSGRAPH_USER_ID` (all read from `.env`). If you need to swap email
   providers, change the `BACKEND` value inside `MAILERS['default']`, not
   the setting name.

## Stack (pinned versions — trust `requirements.txt`, not memory)

| Package | Version | Purpose |
|---|---|---|
| Django | 6.1 | web framework |
| django-msgraphbackend | 5.2.0 | Microsoft Graph email backend, feeds `MAILERS` |
| PyOTP | 2.10.0 | TOTP secret generation + verification |
| qrcode / pillow | 8.2 / 12.3.0 | QR code rendering for enrollment |
| whitenoise | 6.12.0 | static file serving |
| gunicorn | 26.0.0 | WSGI server for non-dev deployment |
| python-dotenv | 1.2.3 | loads `TOTP/.env` (imported as `dotenv` in `settings.py`) |

Python 3.12+. SQLite by default (`TOTP/db.sqlite3`, gitignored).

Note: `requirements.txt` is UTF-16 encoded (this predates any agent
touching it — don't be thrown off by `cat` showing spaced-out characters;
use `iconv -f UTF-16 -t UTF-8` or just edit it with a normal text tool that
handles the encoding, and preserve the encoding on save. Don't try to
"fix" it to UTF-8 unless the user asks — check with the user first since
tooling elsewhere may depend on it).

## Project layout

```
Vixxing/
├── requirements.txt
└── TOTP/                     # Django project root — run manage.py from here
    ├── manage.py
    ├── .env.example          # copy to TOTP/.env, fill in secrets
    ├── TOTP/                 # settings.py, urls.py, wsgi.py, asgi.py
    └── verify/               # the only app — see verify/AGENTS.md
```

There is exactly one Django app: `verify`. Everything product-relevant
(models, views, URLs, templates, tests) lives under `TOTP/verify/`. Read
`TOTP/verify/AGENTS.md` before working there.

## Running things

```bash
cd TOTP
python manage.py migrate
python manage.py test          # runs verify/tests.py
python manage.py runserver 0.0.0.0:8000
```

`manage.py` lives in `TOTP/`, not the repo root — commands must be run from
`TOTP/`, or with `TOTP/manage.py` as the explicit path.

Required env vars live in `TOTP/.env` (see `.env.example` and the README's
env var table): `SECRET_KEY`, `MSGRAPH_TENANT_ID`, `MSGRAPH_CLIENT_ID`,
`MSGRAPH_CLIENT_SECRET`, `MSGRAPH_USER_ID`, `DEFAULT_FROM_EMAIL`. No real
credentials live in the repo; `.env` is gitignored.

## Known inconsistency — don't silently "fix" this without asking

`verify/views.py`'s `_send_enrollment_email()` hardcodes
`from_email='company@domain.com'` and `issuer_name='Company HelpDesk'`
directly in code, while `settings.py` defines `DEFAULT_FROM_EMAIL` from
the environment and is never used by that function. The README calls
these out under "A few strings are hardcoded — change them for your org"
as intentionally cosmetic placeholders for downstream deployers to edit,
not settings-driven. If a task touches email sending, don't assume this is
a bug to quietly wire up to `DEFAULT_FROM_EMAIL` — ask, since it may be
deliberate that the org customizes source directly.

Similarly, `settings.py` currently ships `DEBUG = False`, while the README
describes the shipped default as `DEBUG = True`. Treat `settings.py` as
the source of truth over the README's prose; flag the mismatch to the
user rather than "correcting" either file on your own initiative.

## Security posture

This app is **LAN-only by design**, not hardened for the public internet
(see README's "Scope and security posture" section). `ALLOWED_HOSTS =
['*']` and cookies without `SECURE` flags are intentional for that
context, not oversights to "fix" reflexively. The database holds TOTP
secrets — treat `db.sqlite3` and anything in `.env` as sensitive; never
log or print `mfa_secret` values.

## Conventions

- Every view in `verify/views.py` is decorated `@staff_member_required`;
  mutating endpoints also use `@require_POST`. New endpoints should follow
  the same pattern.
- Bulk-action endpoints (`bulk_enroll_employees`, etc.) take a JSON body
  `{"user_ids": [...]}`, parsed via the `_parse_id_list` helper — reuse it
  rather than re-implementing ID parsing.
- All employee-scoped queries filter `groups__name='Employees'` to keep
  staff/admin accounts out of employee-management endpoints. Keep doing
  this on any new query touching `User`.
- Tests use Django's `TestCase` + `self.client`, and mock outbound email
  by patching `django.core.mail.message.EmailMessage.send` rather than
  hitting Microsoft Graph. Follow that pattern for new email-sending tests
  — don't make tests depend on real Graph credentials.
