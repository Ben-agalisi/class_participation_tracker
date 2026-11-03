import os
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .admin import StudentAdminForm, send_participation_sms
from .index_security import hash_index_number
from .models import ParticipationLog, StaffInvitation, StaffSeat, Student


class ParticipationSmsTests(SimpleTestCase):
	def setUp(self):
		self.student = SimpleNamespace(
				pk=7,
				full_name='Ama Mensah',
				phone_number='0241234567',
		)

	def test_sends_arkesel_get_request(self):
		with patch.dict(os.environ, {
				'SMS_GATEWAY_URL': 'https://sms.arkesel.com/sms/api',
				'SMS_API_KEY': 'test-key',
				'SMS_SENDER_ID': 'COM_ARCH',
		}), patch('participation.admin.urlopen') as gateway_call:
			result = send_participation_sms(self.student, 2)

		self.assertEqual(result, 'sent')
		request_url = gateway_call.call_args.args[0]
		parsed_url = urlparse(request_url)
		self.assertEqual(parsed_url.netloc, 'sms.arkesel.com')
		self.assertEqual(parsed_url.path, '/sms/api')
		parameters = parse_qs(parsed_url.query)
		self.assertEqual(parameters['action'], ['send-sms'])
		self.assertEqual(parameters['api_key'], ['test-key'])
		self.assertEqual(parameters['to'], [self.student.phone_number])
		self.assertEqual(parameters['from'], ['COM_ARCH'])
		self.assertIn('2 marks', parameters['sms'][0])

	def test_does_not_send_without_gateway_configuration(self):
		with patch.dict(os.environ, {
				'SMS_GATEWAY_URL': '',
				'SMS_API_KEY': '',
		}), patch('participation.admin.urlopen') as gateway_call:
			result = send_participation_sms(self.student, 1)

		self.assertEqual(result, 'not_configured')
		gateway_call.assert_not_called()


class AddMarksWorkflowTests(TestCase):
	def setUp(self):
		call_command('setup_mark_entry_role')
		staff_user = get_user_model().objects.create_user(
				username='staff', password='test-password', is_staff=True
		)
		staff_user.groups.add(staff_user.groups.model.objects.get(name='Mark Entry Staff'))
		from .models import StaffSeat
		StaffSeat.objects.create(user=staff_user)
		self.client.force_login(staff_user)
		self.student = Student.objects.create(
				full_name='Benjamin Mensah',
				index_number='UEB12345',
				phone_number='0241234567',
				total_points=8,
		)

	def test_search_returns_matching_student(self):
		response = self.client.get(
				reverse('student_search_api'), {'q': 'Benjamin'}
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()['students'][0]['id'], self.student.id)

	def test_search_matches_phone_number(self):
		response = self.client.get(
				reverse('student_search_api'), {'q': '024123'}
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()['students'][0]['id'], self.student.id)

	def test_search_matches_exact_hashed_index_number(self):
		response = self.client.get(
				reverse('student_search_api'), {'q': 'ueb12345'}
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()['students'][0]['id'], self.student.id)

	def test_search_matches_last_four_index_digits(self):
		response = self.client.get(
				reverse('student_search_api'), {'q': '2345'}
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual([item['id'] for item in response.json()['students']], [self.student.id])

	def test_last_four_search_returns_all_students_with_matching_suffix(self):
		second_student = Student.objects.create(
				full_name='Ama Owusu',
				index_number='UEB9992345',
				phone_number='0201234567',
		)

		response = self.client.get(
				reverse('student_search_api'), {'q': '2345'}
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(
				{item['id'] for item in response.json()['students']},
				{self.student.id, second_student.id},
		)

	def test_last_four_search_is_shown_on_mark_entry_page(self):
		response = self.client.get(reverse('add_marks'), {'q': '2345'})

		self.assertContains(response, 'Benjamin Mensah')
		self.assertContains(response, 'UEB12345')

	def test_student_export_download_includes_names_index_numbers_and_marks(self):
		response = self.client.get(reverse('student_export_csv'))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
		self.assertIn('attachment; filename="student_records.csv"', response['Content-Disposition'])
		content = response.content.decode('utf-8').splitlines()
		self.assertIn('full_name,index_number,total_points', content[0])
		self.assertIn('Benjamin Mensah,UEB12345,8', '\n'.join(content))

	def test_page_renders_select_link_without_javascript(self):
		response = self.client.get(
				reverse('add_marks'), {'q': 'Benjamin'}
		)

		self.assertContains(response, 'Benjamin Mensah')
		self.assertContains(
				response,
				f'href="{reverse("add_marks")}?student_id={self.student.id}"',
		)
		self.assertContains(response, "document.addEventListener('DOMContentLoaded'")

	def test_selecting_student_shows_allocation_form(self):
		response = self.client.get(
				reverse('add_marks'), {'student_id': self.student.id}
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context['selected_student'], self.student)
		self.assertEqual(response.context['remaining_points'], 2)

	def test_rejects_allocation_that_would_exceed_ten_total_marks(self):
		response = self.client.post(
				f'{reverse("add_marks")}?student_id={self.student.id}',
				{'points': '3'},
		)

		self.student.refresh_from_db()
		self.assertEqual(response.status_code, 200)
		self.assertEqual(self.student.total_points, 8)
		self.assertEqual(ParticipationLog.objects.count(), 0)
		self.assertIn('at most 2 more marks', response.context['error'])

	def test_rejects_more_than_ten_marks_in_one_submission(self):
		self.student.total_points = 0
		self.student.save(update_fields=['total_points'])
		response = self.client.post(
				f'{reverse("add_marks")}?student_id={self.student.id}',
				{'points': '11'},
		)

		self.student.refresh_from_db()
		self.assertEqual(response.status_code, 200)
		self.assertEqual(self.student.total_points, 0)
		self.assertEqual(ParticipationLog.objects.count(), 0)
		self.assertIn('no more than 10 marks', response.context['error'])

	def test_saves_valid_marks_with_selected_student_in_post_url(self):
		with patch('participation.admin.send_participation_sms', return_value='sent'):
			response = self.client.post(
					f'{reverse("add_marks")}?student_id={self.student.id}',
					{'points': '2'},
			)

		self.student.refresh_from_db()
		self.assertEqual(response.status_code, 200)
		self.assertEqual(self.student.total_points, 10)
		self.assertEqual(ParticipationLog.objects.get().points_changed, 2)

	def test_admin_form_edits_index_number_without_plaintext_storage(self):
		form = StudentAdminForm(
				data={
						'full_name': self.student.full_name,
						'index_number': 'UEB54321',
						'phone_number': self.student.phone_number,
						'total_points': self.student.total_points,
				},
				instance=self.student,
		)

		self.assertTrue(form.is_valid(), form.errors)
		student = form.save()
		student.refresh_from_db()
		self.assertEqual(student.index_number, 'UEB54321')
		self.assertNotIn('UEB54321', student.index_number_encrypted)
		self.assertEqual(student.index_number_hash, hash_index_number('UEB54321'))


class StudentRegistrationTests(TestCase):
	def registration_data(self, **overrides):
		data = {
				'full_name': '  Akua  Mensah ',
				'index_number': 'ueb98765',
				'phone_number': '024 123-4567',
				'consent': 'on',
				'website': '',
		}
		data.update(overrides)
		return data

	def test_public_registration_creates_admin_student_record(self):
		response = self.client.post(
				reverse('student_registration'), self.registration_data()
		)

		self.assertRedirects(response, reverse('student_registration'))
		student = Student.objects.get(
				index_number_hash=hash_index_number('UEB98765')
		)
		self.assertEqual(student.full_name, 'Akua Mensah')
		self.assertEqual(student.index_number, 'UEB98765')
		self.assertNotIn('UEB98765', student.index_number_encrypted)
		self.assertEqual(student.phone_number, '0241234567')
		self.assertTrue(student.registration_consent)
		self.assertIsNotNone(student.registration_consent_at)
		self.assertEqual(student.total_points, 0)

	def test_registration_rejects_duplicate_index_number(self):
		Student.objects.create(
				full_name='Existing Student',
				index_number='UEB98765',
				phone_number='0201234567',
		)

		response = self.client.post(
				reverse('student_registration'), self.registration_data()
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(
				Student.objects.filter(
						index_number_hash=hash_index_number('UEB98765')
				).count(),
				1,
		)
		self.assertContains(response, 'index number is already registered')

	def test_registration_rejects_phone_number_already_in_use(self):
		Student.objects.create(
				full_name='Existing Student',
				index_number='UEB12345',
				phone_number='024-123-4567',
		)

		response = self.client.post(
				reverse('student_registration'),
				self.registration_data(index_number='UEB98765'),
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(Student.objects.count(), 1)
		self.assertContains(response, 'This phone number is already registered')

	def test_registration_requires_consent(self):
		response = self.client.post(
				reverse('student_registration'),
				self.registration_data(consent=''),
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(Student.objects.count(), 0)
		self.assertContains(response, 'This field is required')

	def test_registration_renders_public_page(self):
		response = self.client.get(reverse('student_registration'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Register your details')
		self.assertContains(response, 'csrfmiddlewaretoken')

	def test_registration_post_requires_csrf_token(self):
		csrf_client = Client(enforce_csrf_checks=True)
		response = csrf_client.post(
				reverse('student_registration'), self.registration_data()
		)

		self.assertEqual(response.status_code, 403)
		self.assertEqual(Student.objects.count(), 0)

	def test_student_search_requires_staff_login(self):
		response = Client().get(
				reverse('student_search_api'), {'q': 'Benjamin'}
		)

		self.assertEqual(response.status_code, 302)
		self.assertIn('/admin/login/', response['Location'])


class StaffInvitationTests(TestCase):
	def setUp(self):
		self.admin_user = get_user_model().objects.create_superuser(
				username='rootadmin', password='test-password', email='root@example.com'
		)
		self.client.force_login(self.admin_user)
		call_command('setup_mark_entry_role')

	def make_invitation(self, email='rep@example.com', token='invitation-token'):
		import hashlib
		from datetime import timedelta
		from django.utils import timezone
		from .models import StaffInvitation

		return StaffInvitation.objects.create(
				email=email,
				token_hash=hashlib.sha256(token.encode()).hexdigest(),
				created_by=self.admin_user,
				expires_at=timezone.now() + timedelta(hours=1),
		)

	def signup_data(self, token='invitation-token', username='markrep'):
		return {
				'token': token,
				'username': username,
				'password1': 'A-long-test-password-938!',
				'password2': 'A-long-test-password-938!',
				'website': '',
		}

	def test_invited_person_creates_single_active_mark_staff_account(self):
		invitation = self.make_invitation()
		response = self.client.post(reverse('staff_signup'), self.signup_data())

		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.context['created'])
		user = get_user_model().objects.get(username='markrep')
		self.assertEqual(user.email, invitation.email)
		self.assertTrue(user.is_active)
		self.assertTrue(user.is_staff)
		self.assertFalse(user.is_superuser)
		self.assertTrue(user.groups.filter(name='Mark Entry Staff').exists())
		self.assertTrue(hasattr(user, 'mark_entry_seat'))
		self.assertIsNotNone(invitation.__class__.objects.get(pk=invitation.pk).used_at)

	def test_invited_account_can_enter_marks_and_view_logs(self):
		self.make_invitation()
		self.client.post(reverse('staff_signup'), self.signup_data())
		user = get_user_model().objects.get(username='markrep')
		self.client.force_login(user)

		response = self.client.get(reverse('add_marks'))

		self.assertEqual(response.status_code, 200)
		self.assertTrue(user.has_perm('participation.award_marks'))
		self.assertTrue(user.has_perm('participation.view_participationlog'))
		self.assertFalse(user.has_perm('auth.add_user'))
		self.assertFalse(user.has_perm('auth.add_group'))

	def test_expired_invitation_cannot_be_claimed(self):
		from datetime import timedelta
		from django.utils import timezone

		invitation = self.make_invitation()
		invitation.expires_at = timezone.now() - timedelta(seconds=1)
		invitation.save(update_fields=['expires_at'])

		response = self.client.post(reverse('staff_signup'), self.signup_data())

		self.assertEqual(response.status_code, 400)
		self.assertEqual(get_user_model().objects.filter(username='markrep').count(), 0)

	def test_invitation_can_only_be_used_once(self):
		self.make_invitation()
		self.client.post(reverse('staff_signup'), self.signup_data())

		response = self.client.post(reverse('staff_signup'), self.signup_data(username='second'))

		self.assertEqual(response.status_code, 400)
		self.assertFalse(get_user_model().objects.filter(username='second').exists())

	def test_same_email_can_be_invited_again_after_staff_account_is_deleted(self):
		from .models import StaffInvitation, StaffSeat

		self.make_invitation()
		self.client.post(reverse('staff_signup'), self.signup_data())
		staff_user = get_user_model().objects.get(username='markrep')
		delete_url = reverse('admin:auth_user_delete', args=[staff_user.pk])
		delete_confirmation = self.client.get(delete_url)
		self.assertEqual(delete_confirmation.status_code, 200)
		self.assertNotContains(delete_confirmation, 'Cannot delete user')
		self.assertEqual(self.client.post(delete_url, {'post': 'yes'}).status_code, 302)

		self.assertFalse(StaffSeat.objects.exists())
		add_url = reverse('admin:participation_staffinvitation_add')
		self.assertEqual(self.client.get(add_url).status_code, 200)
		with override_settings(
				EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
				DEFAULT_FROM_EMAIL='noreply@example.test',
		):
			self.assertEqual(
					self.client.post(add_url, {'email': 'rep@example.com'}).status_code,
					302,
			)
		self.assertEqual(
				StaffInvitation.objects.filter(email='rep@example.com').count(), 2
		)

	def test_second_invitation_cannot_claim_the_single_staff_seat(self):
		from .models import StaffInvitation

		self.make_invitation()
		self.client.post(reverse('staff_signup'), self.signup_data())
		second_token = 'second-invitation'
		self.make_invitation(email='other@example.com', token=second_token)

		response = self.client.post(
				reverse('staff_signup'),
				self.signup_data(token=second_token, username='second'),
		)

		self.assertEqual(response.status_code, 409)
		self.assertFalse(get_user_model().objects.filter(username='second').exists())
		self.assertEqual(StaffInvitation.objects.filter(used_at__isnull=False).count(), 1)

	def test_seat_database_constraint_prevents_a_second_seat(self):
		from django.db import IntegrityError, transaction
		from .models import StaffSeat

		self.make_invitation()
		self.client.post(reverse('staff_signup'), self.signup_data())
		second = get_user_model().objects.create_user(username='second-seat')
		with self.assertRaises(IntegrityError), transaction.atomic():
			StaffSeat.objects.create(slot=2, user=second)

	def test_setup_command_grants_award_flow_only(self):
		user = get_user_model().objects.create_user(username='roleuser', is_staff=True)
		user.groups.add(user.groups.model.objects.get(name='Mark Entry Staff'))

		self.assertTrue(user.has_perm('participation.view_student'))
		self.assertTrue(user.has_perm('participation.view_participationlog'))
		self.assertTrue(user.has_perm('participation.award_marks'))
		self.assertFalse(user.has_perm('participation.add_participationlog'))
		self.assertFalse(user.has_perm('auth.add_user'))
		self.assertFalse(user.has_perm('auth.change_user'))
		self.assertFalse(user.has_perm('auth.add_group'))

	@override_settings(
			EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
			DEFAULT_FROM_EMAIL='noreply@example.test',
	)
	def test_superuser_invitation_emails_private_claim_link(self):
		response = self.client.post(
				reverse('admin:participation_staffinvitation_add'),
				{'email': 'rep@example.com'},
		)

		self.assertEqual(response.status_code, 302)
		self.assertEqual(len(mail.outbox), 1)
		self.assertIn('rep@example.com', mail.outbox[0].to)
		self.assertIn('/staff-signup/?token=', mail.outbox[0].body)
		invitation = StaffInvitation.objects.get(email='rep@example.com')
		self.assertEqual(len(invitation.token_hash), 64)
		self.assertNotIn(invitation.token_hash, mail.outbox[0].body)

	def test_invitation_admin_hidden_after_seat_is_claimed(self):
		self.make_invitation()
		self.client.post(reverse('staff_signup'), self.signup_data())

		response = self.client.get(
				reverse('admin:participation_staffinvitation_add')
		)

		self.assertEqual(response.status_code, 403)


class PasswordRecoveryTests(TestCase):
	@override_settings(
			EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
			DEFAULT_FROM_EMAIL='noreply@example.test',
	)
	def test_admin_login_offers_password_reset_and_email_is_sent(self):
		user = get_user_model().objects.create_user(
				username='markrep',
				password='A-long-test-password-938!',
				email='rep@example.com',
				is_active=True,
			)
		response = self.client.get(reverse('admin:login'))
		self.assertContains(response, reverse('password_reset'))

		response = self.client.post(
				reverse('password_reset'), {'email': user.email}
		)

		self.assertRedirects(response, reverse('password_reset_done'))
		self.assertEqual(len(mail.outbox), 1)
		self.assertIn('rep@example.com', mail.outbox[0].to)
		self.assertIn('/accounts/reset/', mail.outbox[0].body)

	@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
	def test_password_reset_response_does_not_disclose_unknown_email(self):
		response = self.client.post(
				reverse('password_reset'), {'email': 'unknown@example.com'}
		)

		self.assertRedirects(response, reverse('password_reset_done'))
		self.assertEqual(len(mail.outbox), 0)


class AdminLogoutTests(TestCase):
	def test_admin_header_renders_csrf_logout_form(self):
		user = get_user_model().objects.create_superuser(
				username='admin',
				password='test-password',
				email='admin@example.com',
		)
		self.client.force_login(user)

		response = self.client.get(reverse('admin:index'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'method="post" action="/admin/logout/"')
		self.assertContains(response, 'name="csrfmiddlewaretoken"')

	def test_post_logout_clears_authenticated_session(self):
		user = get_user_model().objects.create_superuser(
				username='admin',
				password='test-password',
				email='admin@example.com',
		)
		self.client.force_login(user)

		response = self.client.post(reverse('admin:logout'))

		self.assertEqual(response.status_code, 200)
		self.assertNotIn('_auth_user_id', self.client.session)
