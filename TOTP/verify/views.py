import pyotp
import qrcode
import io
import csv
import json
import logging
import email.utils
from base64 import b64encode
from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.core.mail import EmailMultiAlternatives
from email.message import MIMEPart
from django.template.loader import render_to_string
from .models import EmployeeMFA
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.models import User
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_POST
from django.contrib.auth.models import Group

logger = logging.getLogger(__name__)


def _unique_username(base):
    """Appends a numeric suffix until the username is unique."""
    username = base
    suffix = 1
    while User.objects.filter(username=username).exists():
        username = f"{base}_{suffix}"
        suffix += 1
    return username


def _is_enrolled(user):
    return user.employeemfa.is_enrolled if hasattr(user, 'employeemfa') else False


def _user_summary(user, is_enrolled):
    return {
        'id': user.id,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'full_name': user.get_full_name() or user.username,
        'email': user.email,
        'is_enrolled': is_enrolled,
    }


def _parse_id_list(request):
    """Reads a JSON body of the form {"user_ids": [1, 2, 3]} into a list of ints."""
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        data = {}
    ids = []
    for raw_id in data.get('user_ids', []):
        try:
            ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue
    return ids


class EnrollmentDeliveryError(Exception):
    """Raised when every configured delivery backend failed to send the enrollment email."""

    def __init__(self, failures):
        self.failures = failures  # [(backend_name, error_message), ...], in the order attempted
        super().__init__(f"Enrollment email delivery failed: {failures}")


def _delivery_backends():
    """Ordered list of (display_name, mailer_alias) to attempt delivery
    through - aliases refer to settings.MAILERS. Graph API ('default') is
    tried first - it authenticates with a short-lived OAuth token rather than
    a standing SMTP password. SMTP ('smtp') is a fallback, attempted only if
    Graph isn't configured or fails, and only if SMTP itself is configured -
    settings.py only defines the 'smtp' mailer at all when EMAIL_HOST is set.
    """
    backends = [('Graph API', 'default')]
    if 'smtp' in settings.MAILERS:
        backends.append(('SMTP', 'smtp'))
    return backends


def _deliver_message(msg):
    """Sends msg through the first configured mailer that succeeds, trying
    each in priority order. Returns (backend_name, prior_failures), where
    prior_failures lists any higher-priority backends that were tried and
    failed first as (name, error_message) pairs. Raises EnrollmentDeliveryError
    (with everything tried) if every configured backend failed, or none are
    configured at all.
    """
    failures = []
    for name, alias in _delivery_backends():
        try:
            msg.send(using=alias)
        except Exception as exc:
            logger.warning("Enrollment email delivery via %s failed: %s", name, exc)
            failures.append((name, str(exc)))
            continue
        return name, failures
    raise EnrollmentDeliveryError(failures)


def _delivery_success_message(delivery_method, prior_failures):
    if not prior_failures:
        return f"Message succeeded via {delivery_method}."
    failed_names = ', '.join(name for name, _ in prior_failures)
    return f"Message succeeded via {delivery_method}, failed via {failed_names}."


def _delivery_failure_message(failures):
    if not failures:
        return "No delivery method is configured. Add Graph API or SMTP credentials to .env."
    failed_names = ', '.join(name for name, _ in failures)
    return f"Message failed via {failed_names}."


def _send_enrollment_email(user, force):
    """Generates (or reuses) an MFA secret and emails the QR code, persisting the
    enrollment only once delivery is confirmed. Raises EnrollmentDeliveryError if
    every configured backend fails, leaving any existing MFA record untouched.
    Returns (qr_png_buffer, delivery_method, prior_failures) - see _deliver_message.
    """
    employee_mfa = EmployeeMFA.objects.filter(user=user).first()
    existing_secret = employee_mfa.mfa_secret if employee_mfa else None

    # Decide whether we need a fresh secret, but hold off writing anything
    # to the database until we know the email actually went out.
    generate_new_secret = not existing_secret or force
    secret = pyotp.random_base32() if generate_new_secret else existing_secret

    # Create the provisioning URI for Microsoft/Google Authenticator
    totp = pyotp.totp.TOTP(secret)
    otp_url = totp.provisioning_uri(
        name=user.email,
        issuer_name='Company HelpDesk'
    )

    # Generate the QR Code
    qr = qrcode.make(otp_url)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    qr_png = buffer.getvalue()

    # --- Build the email (plain-text + HTML, with the QR inline AND attached) ---
    context = {'first_name': (user.first_name or "there").strip()}

    # Content-ID for the inline image. make_msgid() returns it WITH angle brackets;
    # the HTML must reference it WITHOUT them.
    qr_cid = email.utils.make_msgid()
    context['qr_cid'] = qr_cid[1:-1]

    text_body = render_to_string('verify/enrollment_email.txt', context)
    html_body = render_to_string('verify/enrollment_email.html', context)

    msg = EmailMultiAlternatives(
        subject='Set up your HelpDesk MFA (takes about a minute)',
        body=text_body,
        from_email='company@domain.com',
        to=[user.email],
    )
    msg.attach_alternative(html_body, "text/html")

    # Inline copy: MIMEPart marked inline, matched to the HTML by Content-ID.
    inline_img = MIMEPart()
    inline_img.set_content(
        qr_png,
        maintype='image',
        subtype='png',
        disposition='inline',
        cid=qr_cid,
    )
    msg.attach(inline_img)

    # Downloadable copy: the filename/content/mimetype form is unchanged in 6.0.
    msg.attach('enrollment_qr.png', qr_png, 'image/png')

    # Raises EnrollmentDeliveryError if every configured backend fails - callers
    # decide how to report it. Delivery failing must not create or mutate the
    # MFA record.
    delivery_method, prior_failures = _deliver_message(msg)

    # Delivery confirmed - now it's safe to persist the enrollment.
    if generate_new_secret:
        employee_mfa, _ = EmployeeMFA.objects.get_or_create(user=user)
        employee_mfa.mfa_secret = secret
        employee_mfa.is_enrolled = True
        employee_mfa.save()

    return buffer, delivery_method, prior_failures


# Create your views here.
@staff_member_required
@require_POST
def generate_enrollment_qr(request, user_id):
    # Grab the User; the MFA row is only created/updated once the email has
    # actually sent successfully - see _send_enrollment_email.
    user = get_object_or_404(User, id=user_id)
    was_enrolled = _is_enrolled(user)

    force = False
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            force = data.get('force', False)
        except json.JSONDecodeError:
            pass

    try:
        buffer, delivery_method, prior_failures = _send_enrollment_email(user, force)
    except Exception as exc:
        # Delivery failed - the employee stays exactly as enrolled/not-enrolled
        # as before this request.
        if request.method == "POST":
            message = (
                _delivery_failure_message(exc.failures)
                if isinstance(exc, EnrollmentDeliveryError)
                else 'Failed to send enrollment email. No changes were saved.'
            )
            return JsonResponse(
                {
                    'status': 'error',
                    'message': message,
                    'is_enrolled': was_enrolled,
                },
                status=502,
            )
        raise

    # Handle both Dashboard API requests (POST) and manual browser visits (GET)
    if request.method == "POST":
        return JsonResponse({
            'status': 'success',
            'message': _delivery_success_message(delivery_method, prior_failures),
            'is_enrolled': True,
        })

    # Fallback for manual GET requests (e.g., typing /enroll/1/ in the browser)
    buffer.seek(0)
    encoded_img = b64encode(buffer.read()).decode()
    qr_code_data = f'data:image/png;base64,{encoded_img}'
    return render(request, 'verify/enroll.html', {'qr_code_data': qr_code_data})

@staff_member_required
@require_POST
def add_employee(request):
    """Creates a new base Django User for MFA tracking"""
    email = request.POST.get('email', '').strip()
    first_name = request.POST.get('first_name', '').strip()
    last_name = request.POST.get('last_name', '').strip()

    if not email:
        return JsonResponse({'status': 'error', 'message': 'Email required'})

    if User.objects.filter(email=email).exists():
        return JsonResponse({'status': 'error', 'message': 'A user with that email already exists.'})

    username = _unique_username(email.split('@')[0])

    new_user = User.objects.create_user(
        username=username,
        email=email,
        first_name=first_name,
        last_name=last_name
    )

    employee_group, created = Group.objects.get_or_create(name="Employees")
    new_user.groups.add(employee_group)

    return JsonResponse({
        'status': 'success',
        'user': _user_summary(new_user, False),
    })

@staff_member_required
@require_POST
def unenroll_employee(request, user_id):
    """Clears an employee's MFA enrollment, keeping their account intact."""
    user = get_object_or_404(User, id=user_id, groups__name='Employees')
    employee_mfa = EmployeeMFA.objects.filter(user=user).first()
    if employee_mfa:
        employee_mfa.mfa_secret = None
        employee_mfa.is_enrolled = False
        employee_mfa.save()
    return JsonResponse({'status': 'success', 'is_enrolled': False})


@staff_member_required
@require_POST
def delete_employee(request, user_id):
    """Permanently deletes an employee's account, enrolled or not."""
    user = get_object_or_404(User, id=user_id, groups__name='Employees')
    user.delete()
    return JsonResponse({'status': 'success'})

@staff_member_required
@require_POST
def verify_caller(request, user_id):
    if request.method == "POST":
        # FIX 3: Match the exact key sent by the JavaScript payload ('code')
        supplied_code = request.POST.get('code')

        # We can safely use get_object_or_404 here, because if they are verifying,
        # they MUST have been enrolled already.
        employee_mfa = get_object_or_404(EmployeeMFA, user__id=user_id)

        if not employee_mfa.mfa_secret:
            return JsonResponse({'status': 'error', 'message': 'User not enrolled.'})

        # Initialize the TOTP object with the employee's saved secret
        totp = pyotp.TOTP(employee_mfa.mfa_secret)

        # Verify the 6-digit code
        is_valid = totp.verify(supplied_code, valid_window=1)

        if is_valid:
            return JsonResponse({'status': 'success', 'message': 'Caller Verified! Proceed with reset.'})
        else:
            return JsonResponse({'status': 'error', 'message': 'Invalid code. Do not proceed.'})

@staff_member_required
def helpdesk_dashboard(request):
    # FIX 4: Update the related name to match Django's default lowercase model convention
    users = User.objects.filter(groups__name='Employees').select_related('employeemfa')

    return render(request, 'verify/dashboard.html', {'users': users})


@staff_member_required
def export_employees_csv(request):
    """Exports Employees-group users as CSV. Never includes MFA secrets.

    If an "ids" query param (comma-separated user IDs) is present, only those
    employees are exported; otherwise every employee is exported.
    """
    users = User.objects.filter(groups__name='Employees').select_related('employeemfa')

    ids_param = request.GET.get('ids', '').strip()
    if ids_param:
        ids = []
        for raw_id in ids_param.split(','):
            raw_id = raw_id.strip()
            if raw_id.isdigit():
                ids.append(int(raw_id))
        users = users.filter(id__in=ids)

    users = users.order_by('last_name', 'first_name')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="employees.csv"'

    writer = csv.writer(response)
    writer.writerow(['first_name', 'last_name', 'email', 'username', 'is_enrolled'])
    for user in users:
        writer.writerow([user.first_name, user.last_name, user.email, user.username, _is_enrolled(user)])

    return response


@staff_member_required
@require_POST
def import_employees_csv(request):
    """Bulk-creates Employees-group users from an uploaded CSV.

    Only populates the user record (name + email) - never touches MFA secrets
    or sends enrollment emails. Each employee must still be enrolled manually.
    """
    csv_file = request.FILES.get('csv_file')
    if not csv_file:
        return JsonResponse({'status': 'error', 'message': 'No file uploaded.'})

    try:
        decoded = csv_file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        return JsonResponse({'status': 'error', 'message': 'File must be a UTF-8 encoded CSV.'})

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        return JsonResponse({'status': 'error', 'message': 'CSV appears to be empty.'})

    # Normalize header names ("Email", "E-Mail", "email") -> matching keys
    field_map = {(name or '').strip().lower().replace(' ', '_').replace('-', '_'): name for name in reader.fieldnames}
    email_key = field_map.get('email')
    if not email_key:
        return JsonResponse({'status': 'error', 'message': 'CSV must include an "email" column.'})
    first_name_key = field_map.get('first_name')
    last_name_key = field_map.get('last_name')

    employee_group, _ = Group.objects.get_or_create(name="Employees")

    created = []
    skipped = []
    for row in reader:
        email = (row.get(email_key) or '').strip()
        if not email:
            continue
        if User.objects.filter(email=email).exists():
            skipped.append(email)
            continue

        first_name = (row.get(first_name_key) or '').strip() if first_name_key else ''
        last_name = (row.get(last_name_key) or '').strip() if last_name_key else ''
        username = _unique_username(email.split('@')[0])

        new_user = User.objects.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )
        new_user.groups.add(employee_group)

        created.append(_user_summary(new_user, False))

    return JsonResponse({'status': 'success', 'created': created, 'skipped': skipped})


@staff_member_required
@require_POST
def bulk_enroll_employees(request):
    """Sends enrollment emails for every selected employee that isn't enrolled yet."""
    ids = _parse_id_list(request)
    users = User.objects.filter(id__in=ids, groups__name='Employees').select_related('employeemfa')

    enrolled, skipped, failed = [], [], []
    fallback_count = 0
    for user in users:
        if _is_enrolled(user):
            skipped.append(user.id)
            continue
        try:
            _, delivery_method, prior_failures = _send_enrollment_email(user, force=False)
        except Exception as exc:
            message = (
                _delivery_failure_message(exc.failures)
                if isinstance(exc, EnrollmentDeliveryError)
                else 'Failed to send enrollment email.'
            )
            failed.append({'id': user.id, 'email': user.email, 'message': message})
            continue
        if prior_failures:
            fallback_count += 1
        enrolled.append(_user_summary(user, True))

    message = f"Enrolled {len(enrolled)} employee(s)."
    if fallback_count:
        message += f" {fallback_count} used a fallback delivery method."
    if skipped:
        message += f" Skipped {len(skipped)} already enrolled."
    if failed:
        message += f" Failed to email {len(failed)}."

    return JsonResponse({'status': 'success', 'enrolled': enrolled, 'skipped': skipped, 'failed': failed, 'message': message})


@staff_member_required
@require_POST
def bulk_reenroll_employees(request):
    """Regenerates the MFA secret and re-sends the QR email for already-enrolled employees."""
    ids = _parse_id_list(request)
    users = User.objects.filter(id__in=ids, groups__name='Employees').select_related('employeemfa')

    re_enrolled, skipped, failed = [], [], []
    fallback_count = 0
    for user in users:
        if not _is_enrolled(user):
            skipped.append(user.id)
            continue
        try:
            _, delivery_method, prior_failures = _send_enrollment_email(user, force=True)
        except Exception as exc:
            message = (
                _delivery_failure_message(exc.failures)
                if isinstance(exc, EnrollmentDeliveryError)
                else 'Failed to send enrollment email.'
            )
            failed.append({'id': user.id, 'email': user.email, 'message': message})
            continue
        if prior_failures:
            fallback_count += 1
        re_enrolled.append(user.id)

    message = f"Re-enrolled {len(re_enrolled)} employee(s)."
    if fallback_count:
        message += f" {fallback_count} used a fallback delivery method."
    if skipped:
        message += f" Skipped {len(skipped)} not yet enrolled."
    if failed:
        message += f" Failed to email {len(failed)}."

    return JsonResponse({'status': 'success', 're_enrolled': re_enrolled, 'skipped': skipped, 'failed': failed, 'message': message})


@staff_member_required
@require_POST
def bulk_unenroll_employees(request):
    """Clears MFA enrollment for selected employees, keeping their accounts intact."""
    ids = _parse_id_list(request)
    users = User.objects.filter(id__in=ids, groups__name='Employees').select_related('employeemfa')

    unenrolled, skipped = [], []
    for user in users:
        if not _is_enrolled(user):
            skipped.append(user.id)
            continue
        employee_mfa = user.employeemfa
        employee_mfa.mfa_secret = None
        employee_mfa.is_enrolled = False
        employee_mfa.save()
        unenrolled.append(user.id)

    return JsonResponse({'status': 'success', 'unenrolled': unenrolled, 'skipped': skipped})


@staff_member_required
@require_POST
def bulk_delete_employees(request):
    """Permanently deletes selected employees, enrolled or not."""
    ids = _parse_id_list(request)
    users = User.objects.filter(id__in=ids, groups__name='Employees')
    deleted = list(users.values_list('id', flat=True))
    users.delete()
    return JsonResponse({'status': 'success', 'deleted': deleted})
