# Agent notes: verify app

See the root `AGENTS.md` first for project-wide facts (Django 6.1, the
`MAILERS` setting, env vars, running commands). This file is about working
inside this one app.

## What's here

This is the only Django app in the project. It implements:

- `models.py` — `EmployeeMFA`: a `OneToOneField` to `django.contrib.auth.User`
  (`related_name="employeemfa"`, lowercase — reverse access is
  `user.employeemfa`, not `user.employee_mfa` or `user.employeeMFA`),
  holding `mfa_secret` and `is_enrolled`. There is no separate "Employee"
  model — an employee is just a `User` in the `Employees` group.
- `views.py` — all app logic: dashboard, enroll/re-enroll, verify, add/
  delete, CSV import/export, and bulk variants of each. No `forms.py`,
  no DRF/serializers — plain function-based views returning `JsonResponse`
  or rendered templates.
- `urls.py` — namespaced `app_name = 'verify'`; reverse URLs as
  `verify:dashboard`, `verify:enroll_user`, etc.
- `templates/verify/` — `dashboard.html` (the whole staff UI) and the
  enrollment email templates (`.txt` + `.html`, both rendered and sent
  together as multipart/alternative).
- `admin.py` — currently empty (no models registered in Django admin).
  Don't assume `EmployeeMFA` is admin-manageable; it isn't, by design.

## Core invariants — preserve these when touching views.py

- **Email delivery gates persistence.** `_send_enrollment_email()`
  deliberately builds the secret/QR/email and calls `msg.send()` *before*
  writing anything to `EmployeeMFA`. If `.send()` raises, no DB row is
  created or mutated — the `except Exception` handlers in the calling
  views depend on this ordering to report "no changes were saved"
  accurately. Do not reorder this to save-then-send.
- **"Employees" group scoping.** Every view that manages employees
  (`unenroll_employee`, `delete_employee`, and all `bulk_*` views) filters
  on `groups__name='Employees'`, so IDs for non-employee users (e.g. staff
  accounts) are silently ignored rather than acted on — see
  `test_bulk_actions_ignore_ids_outside_the_employees_group` in
  `tests.py`. Keep new employee-management endpoints scoped the same way.
- **CSV export never includes `mfa_secret`.** `export_employees_csv` only
  ever writes `first_name, last_name, email, username, is_enrolled`. Don't
  add the secret to any export/serialization path.
- **CSV import never touches MFA state.** `import_employees_csv` only
  creates bare `User` rows in the `Employees` group; enrollment is always
  a separate, explicit step. Don't fold enrollment into import.
- **`force` controls secret regeneration.** `_send_enrollment_email(user,
  force)` reuses the existing secret unless `force=True` (or none exists
  yet). `generate_enrollment_qr` reads `force` from the POST JSON body;
  `bulk_reenroll_employees` always passes `force=True`, `bulk_enroll_employees`
  always passes `force=False`.

## Testing

`python manage.py test` (run from `TOTP/`) runs `tests.py`. Patterns to
follow for new tests:

- Log in via `self.client.force_login(admin_user)` where `admin_user =
  User.objects.create_superuser(...)` — every view requires
  `@staff_member_required`, so unauthenticated tests will just redirect.
- Build employees with the local `make_employee(email, ...)` helper at the
  top of `tests.py` rather than constructing `User` + `EmployeeMFA`
  separately.
- Mock outbound mail by patching
  `'django.core.mail.message.EmailMessage.send'` — never let tests hit
  the real Microsoft Graph backend (`MAILERS`/`msgraphbackend`). Assert
  on `django.core.mail.outbox` for successful sends.
- Assert both the HTTP response JSON *and* the resulting DB state
  (`EmployeeMFA.objects.get(...)`, `refresh_from_db()`) — existing tests
  check both, e.g. that a failed send leaves `mfa_secret` untouched.

## Frontend

`dashboard.html` is the entire UI — no separate JS build, no frontend
framework/bundler in this repo. Any dashboard behavior changes are edits
to that template directly (inline `<script>`/fetch calls against the JSON
endpoints in `urls.py`).
