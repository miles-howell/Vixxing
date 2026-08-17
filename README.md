# Vixxing

A caller-verification tool for IT help desks. It gives an agent a reliable way
to confirm that the person on the phone is actually the employee they claim to
be **before** resetting a password, resetting MFA, or handing over any other
account access.

The name is a nod to the problem it exists to solve: **vishing** (voice
phishing), where an attacker calls the help desk, impersonates a real employee,
and talks an agent into resetting credentials.

---

## The problem: your help desk is an authentication bypass

Most account-takeover defenses assume the attack comes through a login screen.
The help desk is a different door, and it is usually a weaker one.

A typical vishing call goes like this:

1. The attacker looks up an employee (LinkedIn, a leaked breach dump, the
   company directory) and learns enough to sound legitimate.
2. They call the help desk: *"Hi, this is Jordan from Accounting. I got a new
   phone and I'm locked out — can you reset my MFA?"*
3. The agent tries to verify identity using whatever is on hand:
   - **Caller ID** — trivially spoofed.
   - **Employee ID, date of birth, manager's name, last four of an SSN** — all
     findable, leaked, or guessable.
   - **"Security questions"** — often the same information, and frequently
     shared across systems.
4. Under time pressure and a friendly tone, the agent resets the account. The
   attacker now owns it.

None of the checks above prove *possession of anything*. They prove the caller
knows facts, and facts leak. Several of the most damaging breaches in recent
years started exactly here — not with a cracked password, but with a convincing
phone call to a help desk.

## The fix: make the caller prove possession, live, on the call

Vixxing puts a **possession factor on the phone call itself.**

Every employee enrolls a TOTP secret — the same time-based one-time-password
standard (RFC 6238) that authenticator apps already use for login MFA. The
secret lives on the employee's phone and, encrypted at rest by nothing more
than your database controls, on the Vixxing server.

When that employee calls the help desk:

1. The agent pulls them up on the dashboard.
2. The agent asks them to read the current 6-digit code from their authenticator
   app.
3. The agent types the code in and clicks **Verify**.
4. The server checks the code against the employee's stored secret, allowing for
   the current 30-second window plus one on either side for clock drift.
5. The agent sees a green **✓ Caller Verified** or a red **✗ Do not proceed** —
   and acts accordingly.

A caller who cannot produce a live, rotating code from the enrolled device is
not the employee, no matter how much background detail they recite. The check
takes a few seconds and it does not depend on any fact that can be looked up or
leaked.

This is deliberately the same mechanism your users may already know from login
MFA, so the ask on a support call ("read me the 6-digit code") is familiar and
fast.

---

## How it works

Vixxing is a small Django application with a single staff-facing dashboard.

### Enrollment

1. An agent adds an employee (first name, last name, email) on the dashboard, or
   the employee already exists in the **Employees** group.
2. The agent clicks **Email QR Code**. The server:
   - generates a random base32 TOTP secret with [PyOTP](https://github.com/pyauth/pyotp),
   - builds an `otpauth://` provisioning URI,
   - renders it to a QR code, and
   - emails the employee a message with the QR both inline and attached as
     `enrollment_qr.png`.
3. The employee scans the QR with Microsoft Authenticator, Google Authenticator,
   or any RFC 6238 compatible app. They are now enrolled, and their app shows a
   6-digit code that rotates every 30 seconds.

### Verification (the everyday action)

On any support call, the agent finds the employee, asks for the current code,
types it in, and clicks **Verify**. The result is immediate and unambiguous.

### Management

- **Regenerate QR** — issues a new secret and re-emails it (invalidates the old
  device). Use this when someone changes phones or you suspect a secret is
  compromised.
- **Unenroll** — deletes the employee record and their secret entirely.

### Who can use it

Every view is protected by Django's `@staff_member_required`. Help desk agents
log in as Django **staff** users; the built-in Django admin at `/admin/` is used
to create those accounts and manage employees. There is no self-service portal —
this is an internal tool for agents.

---

## Tech stack

| Piece            | What it's for                                              |
| ---------------- | ---------------------------------------------------------- |
| Django 6.1       | Web framework, auth, admin, ORM                            |
| PyOTP            | TOTP secret generation and code verification               |
| qrcode + Pillow  | Rendering enrollment QR codes                              |
| django-msgraphbackend | Sending enrollment email through the Microsoft Graph API |
| SQLite           | Default datastore (swap for Postgres/MySQL if you prefer)  |
| WhiteNoise       | Serving static files                                       |
| Gunicorn         | WSGI server for anything beyond the dev server             |

Project layout:

```
Vixxing/
├── requirements.txt
└── TOTP/                     # Django project root (run manage.py from here)
    ├── manage.py
    ├── .env.example          # copy to .env and fill in — see setup
    ├── TOTP/                 # settings, URLs, WSGI/ASGI
    └── verify/               # the app: dashboard, enrollment, verification
        ├── models.py         # EmployeeMFA (secret + enrollment flag)
        ├── views.py          # enroll / verify / add / unenroll / dashboard
        ├── urls.py
        └── templates/verify/ # dashboard + enrollment email templates
```

---

## First-time setup

### Prerequisites

- Python 3.12+
- An email-sending path. The repo is wired for **Microsoft Graph** out of the
  box (see the next section), but any Django email backend works — see
  [Swapping the email backend](#swapping-the-email-backend).

### Steps

```bash
# 1. Clone
git clone https://github.com/miles-howell/vixxing.git
cd vixxing

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cd TOTP
cp .env.example .env
# edit .env — see the table below

# 5. Create the database
python manage.py migrate

# 6. Create your first staff/admin login
python manage.py createsuperuser

# 7. Run it (bind to the LAN interface so agents can reach it)
python manage.py runserver 0.0.0.0:8000
```

Then:

- Log in at `http://<server-ip>:8000/admin/` with the superuser you just made.
- Open the dashboard at `http://<server-ip>:8000/` and start adding employees.

For anything longer-lived than a quick test, run it under Gunicorn instead of
the dev server, behind an internal reverse proxy.

### Environment variables

Create `TOTP/.env` with the following. The app reads all of these; the shipped
`.env.example` is a starting point and does not list every one.

| Variable              | Required | What it is                                                                 |
| --------------------- | -------- | -------------------------------------------------------------------------- |
| `SECRET_KEY`          | Yes      | Django secret key. Generate a fresh, random one — do not reuse an example. |
| `MSGRAPH_TENANT_ID`   | Graph    | Azure/Entra tenant (directory) ID.                                         |
| `MSGRAPH_CLIENT_ID`   | Graph    | Application (client) ID of your app registration.                          |
| `MSGRAPH_CLIENT_SECRET` | Graph  | Client secret for that app registration.                                   |
| `MSGRAPH_USER_ID`     | Graph    | The mailbox (user ID or UPN) enrollment mail is sent **from**.             |
| `DEFAULT_FROM_EMAIL`  | Graph    | Default From address Django uses.                                          |

Generate a Django secret key:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### A few strings are hardcoded — change them for your org

These placeholders live in code, not in `.env`, because they are cosmetic. Edit
them to match your organization before you send real enrollment mail:

- `verify/views.py` — the `from_email`, the TOTP `issuer_name` (shown in the
  authenticator app), and the email subject line.
- `verify/templates/verify/enrollment_email.txt` and `.html` — the message body,
  authenticator-app instructions, and signature.
- The **Employees** group name, if you want to scope the dashboard to a
  different Django group.

---

## What is NOT in this repository

Some things are intentionally absent — because they are secrets, because they
are environment-specific, or because they are yours to provision. **Cloning this
repo does not give anyone access to email or to your directory.**

### Microsoft Graph / Azure credentials (not included)

The app can send enrollment mail through the Microsoft Graph API, but **no
credentials for that ship in this repo, and none are implied.** You provide your
own:

1. In **Microsoft Entra ID** (Azure AD), register an application (this shows up
   as an **Enterprise Application** in your tenant).
2. Grant it the Microsoft Graph **`Mail.Send`** *application* permission and
   have an admin grant tenant admin consent.
3. Create a **client secret** for the app.
4. Put the resulting **tenant ID, client (application) ID, and client secret**
   into your `.env` as shown above, and set `MSGRAPH_USER_ID` to the mailbox you
   want mail sent from.

The application ID and secret are the keys to sending mail as your tenant — they
belong in your `.env`, never in version control.

### Swapping the email backend

Nothing about the design requires Microsoft Graph. Enrollment mail is sent
through Django's normal email machinery, so you can point `MAILERS` /
`EMAIL_BACKEND` in `TOTP/TOTP/settings.py` at plain SMTP or any other Django
email backend and drop the Graph variables entirely. The QR generation and
verification logic do not change.

### Local secrets and state (git-ignored)

The following are excluded by `.gitignore` and must be created per install:

- `TOTP/.env` — all of the above secrets.
- `db.sqlite3` — the database, including enrolled employees and their TOTP
  secrets.
- `staticfiles/` and other collected static output.

---

## Scope and security posture: LAN-only

**This tool is built to run on a trusted internal network. It is not hardened
for the public internet, and you should not expose it there.**

The shipped configuration reflects that intent:

- `DEBUG = True`
- `ALLOWED_HOSTS = ['*']`
- `SESSION_COOKIE_SECURE = False` and `CSRF_COOKIE_SECURE = False` (no HTTPS
  assumed)

Those settings are convenient on a LAN and unsafe on the open internet. Before
this touches anything beyond a trusted internal segment, at minimum you would
need to set `DEBUG = False`, pin `ALLOWED_HOSTS` to real hostnames, terminate
TLS and turn the secure-cookie flags back on, and put it behind proper access
controls (VPN, internal reverse proxy, IP allow-listing). Treat the database as
sensitive: it holds the TOTP secrets that back every verification.

Run it on the inside. Keep it there.

---

## License

Vixxing is released under the **GNU General Public License v3.0**. See the
[`LICENSE`](LICENSE) file for the full text.
