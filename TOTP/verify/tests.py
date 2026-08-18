import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .models import EmployeeMFA


class GenerateEnrollmentQrTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin', email='admin@example.com', password='password'
        )
        self.client.force_login(self.admin)
        self.employee = User.objects.create_user(
            username='employee', email='employee@example.com', password='password'
        )
        self.url = reverse('verify:enroll_user', args=[self.employee.id])

    def test_email_failure_does_not_create_mfa_record(self):
        self.assertFalse(EmployeeMFA.objects.filter(user=self.employee).exists())

        with patch(
            'django.core.mail.message.EmailMessage.send',
            side_effect=Exception('SMTP is down'),
        ):
            response = self.client.post(
                self.url,
                data=json.dumps({'force': False}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['status'], 'error')
        self.assertFalse(response.json()['is_enrolled'])
        self.assertFalse(
            EmployeeMFA.objects.filter(user=self.employee).exists(),
            'No MFA record should be created when the enrollment email fails to send.',
        )

    def test_email_failure_on_regenerate_does_not_change_existing_secret(self):
        employee_mfa = EmployeeMFA.objects.create(
            user=self.employee, mfa_secret='ORIGINALSECRET', is_enrolled=True
        )

        with patch(
            'django.core.mail.message.EmailMessage.send',
            side_effect=Exception('SMTP is down'),
        ):
            response = self.client.post(
                self.url,
                data=json.dumps({'force': True}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 502)
        employee_mfa.refresh_from_db()
        self.assertEqual(employee_mfa.mfa_secret, 'ORIGINALSECRET')
        self.assertTrue(employee_mfa.is_enrolled)

    def test_successful_send_creates_and_enrolls_mfa_record(self):
        response = self.client.post(
            self.url,
            data=json.dumps({'force': False}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        self.assertTrue(response.json()['is_enrolled'])
        self.assertEqual(len(mail.outbox), 1)

        employee_mfa = EmployeeMFA.objects.get(user=self.employee)
        self.assertTrue(employee_mfa.is_enrolled)
        self.assertTrue(employee_mfa.mfa_secret)
