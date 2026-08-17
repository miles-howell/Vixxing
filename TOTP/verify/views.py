import pyotp
import qrcode
import io
import json
import email.utils
from base64 import b64encode
from django.shortcuts import render, get_object_or_404
from django.core.mail import EmailMultiAlternatives
from email.message import MIMEPart
from django.template.loader import render_to_string
from .models import EmployeeMFA
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_POST

# Create your views here.
@staff_member_required
@require_POST
def generate_enrollment_qr(request, user_id):
    # FIX 1: Grab the User, then Get-or-Create the MFA profile to prevent 404s
    user = get_object_or_404(User, id=user_id)
    employee_mfa, created = EmployeeMFA.objects.get_or_create(user=user)

    force = False
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            force = data.get('force', False)
        except json.JSONDecodeError:
            pass

    # Generate a random 32-character base32 secret
    if not employee_mfa.mfa_secret or force:
        employee_mfa.mfa_secret = pyotp.random_base32()
        employee_mfa.is_enrolled = True
        employee_mfa.save()

    # Create the provisioning URI for Microsoft/Google Authenticator
    totp = pyotp.totp.TOTP(employee_mfa.mfa_secret)
    otp_url = totp.provisioning_uri(
        name=employee_mfa.user.email,
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
        to=[employee_mfa.user.email],
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

    msg.send()

    # FIX 2: Handle both Dashboard API requests (POST) and manual browser visits (GET)
    if request.method == "POST":
        return JsonResponse({'status': 'success', 'message': 'Email sent.'})

    # Fallback for manual GET requests (e.g., typing /enroll/1/ in the browser)
    buffer.seek(0)
    encoded_img = b64encode(buffer.read()).decode()
    qr_code_data = f'data:image/png;base64,{encoded_img}'
    return render(request, 'verify/enroll.html', {'qr_code_data': qr_code_data})

@staff_member_required
@require_POST
def add_employee(request):
    """Creates a new base Django User for MFA tracking"""
    if request.method == "POST":
        email = request.POST.get('email')
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')

        if not email:
            return JsonResponse({'status': 'error', 'message': 'Email required'})

        username = email.split('@')[0]
        # Ensure username uniqueness
        if User.objects.filter(username=username).exists():
            username = f"{username}_{User.objects.count()}"

        User.objects.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name
        )
        return JsonResponse({'status': 'success'})

    return JsonResponse({'status': 'error', 'message': 'Invalid method.'})

@staff_member_required
@require_POST
def unenroll_employee(request, user_id):
    """Deletes the user and their MFA record"""
    if request.method == "POST":
        user = get_object_or_404(User, id=user_id)
        user.delete()
        return JsonResponse({'status': 'success'})

    return JsonResponse({'status': 'error', 'message': 'Invalid method.'})

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
    users = User.objects.select_related('employeemfa').all()

    return render(request, 'verify/dashboard.html', {'users': users})
