import json
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .models import EmployeeMFA


def make_employee(email, username=None, enrolled=False, secret=''):
    employee_group, _ = Group.objects.get_or_create(name="Employees")
    user = User.objects.create_user(
        username=username or email.split('@')[0], email=email, password='password'
    )
    user.groups.add(employee_group)
    EmployeeMFA.objects.create(user=user, mfa_secret=secret, is_enrolled=enrolled)
    return user


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


class UnenrollAndDeleteTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin2', email='admin2@example.com', password='password'
        )
        self.client.force_login(self.admin)
        self.employee = make_employee('unenroll@example.com', enrolled=True, secret='SECRET123')

    def test_unenroll_clears_mfa_but_keeps_the_account(self):
        url = reverse('verify:unenroll', args=[self.employee.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        self.assertTrue(User.objects.filter(id=self.employee.id).exists())

        employee_mfa = EmployeeMFA.objects.get(user=self.employee)
        self.assertFalse(employee_mfa.is_enrolled)
        self.assertFalse(employee_mfa.mfa_secret)

    def test_delete_removes_an_enrolled_employee(self):
        url = reverse('verify:delete_employee', args=[self.employee.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(id=self.employee.id).exists())

    def test_delete_removes_a_not_yet_enrolled_employee(self):
        not_enrolled = make_employee('notenrolled@example.com', enrolled=False)
        url = reverse('verify:delete_employee', args=[not_enrolled.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(id=not_enrolled.id).exists())


class BulkActionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin3', email='admin3@example.com', password='password'
        )
        self.client.force_login(self.admin)
        self.not_enrolled = make_employee('bulk-new@example.com', enrolled=False)
        self.enrolled = make_employee('bulk-enrolled@example.com', enrolled=True, secret='EXISTINGSECRET')

    def test_bulk_enroll_only_affects_unenrolled_selected_employees(self):
        url = reverse('verify:bulk_enroll')
        response = self.client.post(
            url,
            data=json.dumps({'user_ids': [self.not_enrolled.id, self.enrolled.id]}),
            content_type='application/json',
        )

        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([u['id'] for u in data['enrolled']], [self.not_enrolled.id])
        self.assertEqual(data['skipped'], [self.enrolled.id])
        self.assertEqual(len(mail.outbox), 1)

        self.not_enrolled.employeemfa.refresh_from_db()
        self.assertTrue(self.not_enrolled.employeemfa.is_enrolled)

    def test_bulk_reenroll_only_affects_enrolled_selected_employees(self):
        url = reverse('verify:bulk_reenroll')
        response = self.client.post(
            url,
            data=json.dumps({'user_ids': [self.not_enrolled.id, self.enrolled.id]}),
            content_type='application/json',
        )

        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['re_enrolled'], [self.enrolled.id])
        self.assertEqual(data['skipped'], [self.not_enrolled.id])
        self.assertEqual(len(mail.outbox), 1)

        self.enrolled.employeemfa.refresh_from_db()
        self.assertNotEqual(self.enrolled.employeemfa.mfa_secret, 'EXISTINGSECRET')

    def test_bulk_unenroll_clears_mfa_without_deleting_accounts(self):
        url = reverse('verify:bulk_unenroll')
        response = self.client.post(
            url,
            data=json.dumps({'user_ids': [self.not_enrolled.id, self.enrolled.id]}),
            content_type='application/json',
        )

        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['unenrolled'], [self.enrolled.id])
        self.assertEqual(data['skipped'], [self.not_enrolled.id])

        self.assertTrue(User.objects.filter(id=self.enrolled.id).exists())
        self.enrolled.employeemfa.refresh_from_db()
        self.assertFalse(self.enrolled.employeemfa.is_enrolled)
        self.assertFalse(self.enrolled.employeemfa.mfa_secret)

    def test_bulk_delete_removes_selected_employees_regardless_of_enrollment(self):
        url = reverse('verify:bulk_delete')
        response = self.client.post(
            url,
            data=json.dumps({'user_ids': [self.not_enrolled.id, self.enrolled.id]}),
            content_type='application/json',
        )

        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(data['deleted'], [self.not_enrolled.id, self.enrolled.id])
        self.assertFalse(User.objects.filter(id=self.not_enrolled.id).exists())
        self.assertFalse(User.objects.filter(id=self.enrolled.id).exists())

    def test_bulk_actions_ignore_ids_outside_the_employees_group(self):
        outsider = User.objects.create_user(username='outsider', email='outsider@example.com', password='password')
        url = reverse('verify:bulk_delete')
        response = self.client.post(
            url,
            data=json.dumps({'user_ids': [outsider.id]}),
            content_type='application/json',
        )

        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['deleted'], [])
        self.assertTrue(User.objects.filter(id=outsider.id).exists())


class ExportEmployeesCsvTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin4', email='admin4@example.com', password='password'
        )
        self.client.force_login(self.admin)
        self.employee_a = make_employee('export-a@example.com', enrolled=True, secret='SECRET')
        self.employee_b = make_employee('export-b@example.com', enrolled=False)

    def test_export_without_ids_includes_every_employee(self):
        response = self.client.get(reverse('verify:export_employees'))
        content = response.content.decode()

        self.assertIn('export-a@example.com', content)
        self.assertIn('export-b@example.com', content)
        self.assertNotIn('SECRET', content)

    def test_export_with_ids_only_includes_selected_employees(self):
        response = self.client.get(reverse('verify:export_employees'), {'ids': str(self.employee_a.id)})
        content = response.content.decode()

        self.assertIn('export-a@example.com', content)
        self.assertNotIn('export-b@example.com', content)
