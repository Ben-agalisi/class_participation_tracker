import hashlib

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.utils import IntegrityError
from django.shortcuts import redirect, render
from django.utils import timezone

from .forms import InvitedStaffSignupForm, StudentRegistrationForm
from .models import StaffInvitation, StaffSeat


def staff_signup_view(request):
	raw_token = request.GET.get('token') or request.POST.get('token', '')
	token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
	now = timezone.now()
	invitation = StaffInvitation.objects.filter(
			token_hash=token_hash,
			used_at__isnull=True,
			expires_at__gt=now,
	).first() if raw_token else None

	if not invitation:
		return render(
				request,
				'participation/staff_signup.html',
				{'invalid_invitation': True},
				status=400,
		)

	if StaffSeat.objects.exists():
		return render(
				request,
				'participation/staff_signup.html',
				{'seat_claimed': True},
				status=409,
		)

	form = InvitedStaffSignupForm(request.POST or None)
	if request.method == 'POST' and form.is_valid():
		if form.cleaned_data['website']:
			return redirect('admin:login')

		try:
			with transaction.atomic():
				invitation = StaffInvitation.objects.select_for_update().filter(
						pk=invitation.pk,
						used_at__isnull=True,
						expires_at__gt=timezone.now(),
				).first()
				mark_entry_group = Group.objects.filter(
						name=settings.MARK_ENTRY_GROUP_NAME
				).first()
				if not invitation or StaffSeat.objects.exists() or not mark_entry_group:
					return render(
							request,
							'participation/staff_signup.html',
							{
									'invalid_invitation': not invitation,
									'seat_claimed': StaffSeat.objects.exists(),
									'role_not_configured': not mark_entry_group,
							},
							status=409,
					)

				user = form.save(commit=False)
				user.email = invitation.email
				user.is_active = True
				user.is_staff = True
				user.is_superuser = False
				user.save()
				user.groups.add(mark_entry_group)
				StaffSeat.objects.create(user=user)
				invitation.used_at = timezone.now()
				invitation.save(update_fields=['used_at'])
		except IntegrityError:
			return render(
					request,
					'participation/staff_signup.html',
					{'seat_claimed': True},
					status=409,
			)

		return render(request, 'participation/staff_signup.html', {'created': True})

	return render(
			request,
			'participation/staff_signup.html',
			{'form': form, 'invited_email': invitation.email, 'token': raw_token},
	)


def student_registration_view(request):
	form = StudentRegistrationForm(request.POST or None)

	if request.method == 'POST' and form.is_valid():
		if form.cleaned_data['website']:
			return redirect('student_registration')

		student = form.save()
		student.registration_consent = True
		student.registration_consent_at = timezone.now()
		student.save()
		messages.success(
				request,
				'Your details have been submitted. The class team can now find your record.',
		)
		return redirect('student_registration')

	return render(
			request,
			'participation/student_registration.html',
			{'form': form},
	)
