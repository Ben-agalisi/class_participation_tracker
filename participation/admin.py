import csv
import hashlib
import logging
import os
import secrets
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings
from django.core.mail import send_mail
from django.core.exceptions import PermissionDenied
from django.db.models import F, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.urls import reverse
from functools import wraps
from .index_security import (
  hash_index_number,
  hash_index_number_last_four,
  normalize_index_number,
)
from .models import ParticipationLog, StaffInvitation, StaffSeat, Student

logger = logging.getLogger(__name__)


def mark_entry_seat_required(view_func):
  @wraps(view_func)
  def wrapped(request, *args, **kwargs):
    user = request.user
    has_seat = user.is_superuser or StaffSeat.objects.filter(user=user).exists()
    if not user.is_authenticated or not user.is_staff or not has_seat:
      raise PermissionDenied
    return view_func(request, *args, **kwargs)
  return wrapped


def send_staff_invitation(invitation, request, token=None):
  token = token or secrets.token_urlsafe(32)
  invitation.token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
  invitation.expires_at = timezone.now() + timedelta(
      minutes=settings.STAFF_INVITATION_TTL_MINUTES
  )
  invitation.save(update_fields=['token_hash', 'expires_at'])

  signup_path = reverse('staff_signup')
  invite_url = request.build_absolute_uri(
      f'{signup_path}?{urlencode({"token": token})}'
  )
  message = (
      'You have been invited to create the class participation mark-entry account.\n\n'
      f'Use this private link to choose your username and password:\n{invite_url}\n\n'
      f'The link expires in {settings.STAFF_INVITATION_TTL_MINUTES} minute(s) and can be used once. '
      'If you were not expecting this invitation, ignore this message.'
  )

  if settings.DEBUG:
    print('\n=== STAFF INVITATION LINK ===')
    print(f'This is your invitation link: {invite_url}')
    print(f'Expires in: {settings.STAFF_INVITATION_TTL_MINUTES} minute(s)')
    print('============================\n')

  send_mail(
      'Class participation staff account invitation',
      message,
      settings.DEFAULT_FROM_EMAIL or None,
      [invitation.email],
      fail_silently=False,
  )


@admin.register(StaffInvitation)
class StaffInvitationAdmin(admin.ModelAdmin):
  list_display = ('email', 'created_at', 'expires_at', 'used_at', 'created_by')
  fields = ('email', 'created_at', 'expires_at', 'used_at', 'created_by')
  readonly_fields = ('created_at', 'expires_at', 'used_at', 'created_by')
  actions = ('resend_unused_invitation',)

  def has_module_permission(self, request):
    return request.user.is_superuser

  def has_view_permission(self, request, obj=None):
    return request.user.is_superuser

  def has_add_permission(self, request):
    active_invitation_exists = StaffInvitation.objects.filter(
        used_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).exists()
    return (
        request.user.is_superuser
        and not StaffSeat.objects.exists()
        and not active_invitation_exists
    )

  def has_change_permission(self, request, obj=None):
    return request.user.is_superuser

  def has_delete_permission(self, request, obj=None):
    return request.user.is_superuser

  def save_model(self, request, obj, form, change):
    if change:
      return
    obj.created_by = request.user
    token = secrets.token_urlsafe(32)
    obj.token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    obj.expires_at = timezone.now() + timedelta(
      minutes=settings.STAFF_INVITATION_TTL_MINUTES
    )
    super().save_model(request, obj, form, change)
    try:
      send_staff_invitation(obj, request, token)
      self.message_user(request, f'Invitation sent to {obj.email}.')
    except Exception:
      logger.exception('Could not send staff invitation email.')
      self.message_user(
          request,
          'The invitation was created, but email delivery failed. Select it and use the resend action after checking email settings.',
          level='error',
      )

  @admin.action(description='Resend selected unused invitation')
  def resend_unused_invitation(self, request, queryset):
    if not request.user.is_superuser or StaffSeat.objects.exists():
      raise PermissionDenied
    sent_count = 0
    for invitation in queryset.filter(used_at__isnull=True):
      try:
        send_staff_invitation(invitation, request)
        sent_count += 1
      except Exception:
        logger.exception('Could not resend staff invitation email.')
    self.message_user(request, f'Resent {sent_count} invitation email(s).')


@admin.register(StaffSeat)
class StaffSeatAdmin(admin.ModelAdmin):
  list_display = ('user', 'created_at')
  readonly_fields = ('slot', 'user', 'created_at')

  def has_module_permission(self, request):
    return request.user.is_superuser

  def has_view_permission(self, request, obj=None):
    return request.user.is_superuser

  def has_add_permission(self, request):
    return False

  def has_change_permission(self, request, obj=None):
    return False

  def has_delete_permission(self, request, obj=None):
    return False


class StaffAccountUserAdmin(UserAdmin):
  def get_deleted_objects(self, objs, request):
    deleted_objects, model_count, perms_needed, protected = super().get_deleted_objects(
        objs, request
    )
    perms_needed.discard(StaffSeat._meta.verbose_name)
    return deleted_objects, model_count, perms_needed, protected


admin.site.unregister(get_user_model())
admin.site.register(get_user_model(), StaffAccountUserAdmin)


class StudentAdminForm(forms.ModelForm):
  index_number = forms.CharField(max_length=50)

  class Meta:
    model = Student
    fields = ('full_name', 'phone_number', 'total_points')

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    if self.instance and self.instance.pk:
      self.fields['index_number'].initial = self.instance.index_number

  def clean_index_number(self):
    index_number = normalize_index_number(self.cleaned_data['index_number'])
    digest = hash_index_number(index_number)
    if Student.objects.exclude(pk=self.instance.pk).filter(
        index_number_hash=digest
    ).exists():
      raise forms.ValidationError('This student index number is already registered.')
    return index_number

  def save(self, commit=True):
    student = super().save(commit=False)
    student.index_number = self.cleaned_data['index_number']
    if commit:
      student.save()
      self.save_m2m()
    return student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
  form = StudentAdminForm
  list_display = ('full_name', 'index_number', 'phone_number', 'total_points')
  search_fields = ('full_name', 'phone_number')

  def get_search_results(self, request, queryset, search_term):
    queryset, may_have_duplicates = super().get_search_results(
        request, queryset, search_term
    )
    normalized_index = normalize_index_number(search_term)
    if normalized_index:
      queryset |= self.model.objects.filter(
          index_number_hash=hash_index_number(normalized_index)
      )
    return queryset, may_have_duplicates


@admin.register(ParticipationLog)
class ParticipationLogAdmin(admin.ModelAdmin):
  list_display = ('student', 'points_changed', 'timestamp')
  list_filter = ('timestamp',)


@staff_member_required
@mark_entry_seat_required
def student_search_api(request):
  query = request.GET.get('q', '')
  results = []
  if query:
    search_filter = (
        Q(full_name__icontains=query)
        | Q(phone_number__icontains=query)
        | Q(index_number_hash=hash_index_number(normalize_index_number(query)))
    )
    if query.isdigit() and len(query) == 4:
      search_filter |= Q(index_number_last_four_hash=hash_index_number_last_four(query))
    students = Student.objects.filter(search_filter).order_by('full_name')
    for s in students[:10]:
      results.append({
          'id': s.id,
          'full_name': s.full_name,
          'index_number': s.index_number,
          'phone_number': s.phone_number,
          'total_points': s.total_points,
      })
  return JsonResponse({'students': results})


@staff_member_required
@mark_entry_seat_required
def student_export_csv(request):
  response = HttpResponse(content_type='text/csv; charset=utf-8')
  response['Content-Disposition'] = 'attachment; filename="student_records.csv"'

  writer = csv.writer(response)
  writer.writerow(['full_name', 'index_number', 'total_points'])

  for student in Student.objects.order_by('full_name'):
    writer.writerow([student.full_name, student.index_number, student.total_points])

  return response


def send_participation_sms(student, points_added):
  """Sends an automated SMS notification to the student's phone number."""
  if not student.phone_number:
    return 'no_phone'

  gateway_url = os.environ.get('SMS_GATEWAY_URL')
  api_key = os.environ.get('SMS_API_KEY')
  sender_id = os.environ.get('SMS_SENDER_ID')
  if not gateway_url or not api_key or not sender_id:
    logger.info('SMS gateway is not configured; notification was not sent.')
    return 'not_configured'

  current_time = timezone.localtime().strftime('%A, %d %B %Y at %I:%M %p')
  mark_label = 'mark' if points_added == 1 else 'marks'
  message = (
      f"Hello {student.full_name}, {points_added} {mark_label} have been added to"
      f" your class participation at {current_time} during the Computer"
      " Architecture class."
  )

  parameters = urlencode({
      'action': 'send-sms',
      'api_key': api_key,
      'to': student.phone_number,
      'from': sender_id,
      'sms': message,
  })
  request_url = f'{gateway_url}?{parameters}'

  try:
    with urlopen(request_url, timeout=10):
      pass
  except (HTTPError, URLError, TimeoutError, OSError) as error:
    logger.warning('SMS gateway request failed (%s).', type(error).__name__)
    return 'failed'

  logger.info('SMS notification sent for student record %s.', student.pk)
  return 'sent'


@staff_member_required
@mark_entry_seat_required
def add_marks_view(request):
  selected_student = None
  student_id = request.GET.get('student_id')
  query = request.GET.get('q', '').strip()
  students = []

  if student_id:
    selected_student = Student.objects.filter(id=student_id).first()

  if query:
    search_filter = (
        Q(full_name__icontains=query)
        | Q(phone_number__icontains=query)
        | Q(index_number_hash=hash_index_number(normalize_index_number(query)))
    )
    if query.isdigit() and len(query) == 4:
      search_filter |= Q(index_number_last_four_hash=hash_index_number_last_four(query))
    students = Student.objects.filter(search_filter).order_by('full_name')[:10]

  if request.method == 'POST' and selected_student:
    try:
      points_to_add = int(request.POST.get('points', ''))
    except (TypeError, ValueError):
      points_to_add = 0

    if points_to_add < 1:
      error = 'Enter a whole number of marks greater than zero.'
    elif points_to_add > 10:
      error = 'You can add no more than 10 marks at a time.'
    elif selected_student.total_points + points_to_add > 10:
      remaining = max(0, 10 - selected_student.total_points)
      error = f'This student can receive at most {remaining} more marks.'
    else:
      error = None

    if error:
      return render(
          request,
          'admin/add_marks.html',
          {
              'title': 'Add Marks to Student',
              'selected_student': selected_student,
              'error': error,
              'query': query,
              'students': students,
              'remaining_points': max(0, 10 - selected_student.total_points),
          },
      )

    # Update cumulative points
    selected_student.total_points = F('total_points') + points_to_add
    selected_student.save()
    selected_student.refresh_from_db()

    # Log timestamp entry
    ParticipationLog.objects.create(
        student=selected_student, points_changed=points_to_add
    )

    sms_status = send_participation_sms(selected_student, points_to_add)
    sms_messages = {
      'sent': 'SMS notification sent.',
      'no_phone': 'Marks were saved, but this student has no phone number.',
      'not_configured': 'Marks were saved. SMS delivery is not configured.',
      'failed': 'Marks were saved, but the SMS could not be delivered.',
    }

    return render(
        request,
        'admin/add_marks.html',
        {
            'title': 'Add Marks to Student',
            'success': True,
            'selected_student': selected_student,
            'points_added': points_to_add,
            'sms_message': sms_messages[sms_status],
            'sms_status': sms_status,
        },
    )

  return render(
      request,
      'admin/add_marks.html',
      {
        'title': 'Add Marks to Student',
        'selected_student': selected_student,
        'query': query,
        'students': students,
        'remaining_points': (
          max(0, 10 - selected_student.total_points)
          if selected_student else 10
        ),
      },
  )