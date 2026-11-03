from django.db import models
from django.conf import settings
from django.utils import timezone

from .index_security import (
  decrypt_index_number,
  encrypt_index_number,
  hash_index_number,
  hash_index_number_last_four,
)


class Student(models.Model):
  full_name = models.CharField(max_length=150)
  index_number_encrypted = models.TextField()
  index_number_hash = models.CharField(max_length=64, unique=True)
  index_number_last_four_hash = models.CharField(
      max_length=64, blank=True, default='', db_index=True
  )
  phone_number = models.CharField(
      max_length=15, help_text="Format: 0241234567"
  )  # <-- Added phone contact
  total_points = models.IntegerField(default=0)
  registration_consent = models.BooleanField(default=False)
  registration_consent_at = models.DateTimeField(null=True, blank=True)

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

  def __str__(self):
    return f"{self.full_name} ({self.index_number})"

  @property
  def index_number(self):
    return decrypt_index_number(self.index_number_encrypted)

  @index_number.setter
  def index_number(self, value):
    self.index_number_encrypted = encrypt_index_number(value)
    self.index_number_hash = hash_index_number(value)
    self.index_number_last_four_hash = hash_index_number_last_four(value)

  def record_registration_consent(self):
    self.registration_consent = True
    self.registration_consent_at = timezone.now()


class ParticipationLog(models.Model):
  student = models.ForeignKey(Student, on_delete=models.CASCADE)
  points_changed = models.IntegerField()
  timestamp = models.DateTimeField(auto_now_add=True)

  class Meta:
    permissions = [
        ('award_marks', 'Can award participation marks'),
    ]

  def __str__(self):
    return f"{self.student.full_name} - {self.points_changed} pts at {self.timestamp}"


class StaffInvitation(models.Model):
  email = models.EmailField()
  token_hash = models.CharField(max_length=64, unique=True)
  created_by = models.ForeignKey(
      settings.AUTH_USER_MODEL,
      on_delete=models.PROTECT,
      related_name='staff_invitations_created',
  )
  created_at = models.DateTimeField(auto_now_add=True)
  expires_at = models.DateTimeField()
  used_at = models.DateTimeField(null=True, blank=True)

  def __str__(self):
    return self.email


class StaffSeat(models.Model):
  slot = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
  user = models.OneToOneField(
      settings.AUTH_USER_MODEL,
      on_delete=models.CASCADE,
      related_name='mark_entry_seat',
  )
  created_at = models.DateTimeField(auto_now_add=True)

  class Meta:
    constraints = [
        models.CheckConstraint(condition=models.Q(slot=1), name='single_mark_entry_seat'),
    ]

  def __str__(self):
    return self.user.get_username()