import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

from .index_security import hash_index_number, normalize_index_number
from .models import Student


class InvitedStaffSignupForm(UserCreationForm):
  website = forms.CharField(required=False, widget=forms.HiddenInput)

  class Meta(UserCreationForm.Meta):
    model = get_user_model()
    fields = ('username',)


class StudentRegistrationForm(forms.Form):
  full_name = forms.CharField(
    max_length=150,
    label='Full name',
    widget=forms.TextInput(attrs={
      'autocomplete': 'name',
      'placeholder': 'As shown in your student records',
      'maxlength': 150,
    }),
  )
  index_number = forms.CharField(
    max_length=50,
    label='Student index number',
    widget=forms.TextInput(attrs={
      'autocomplete': 'off',
      'placeholder': 'Enter your unique index number',
      'maxlength': 50,
    }),
  )
  phone_number = forms.CharField(
    max_length=15,
    label='Phone number',
    widget=forms.TelInput(attrs={
      'autocomplete': 'tel',
      'inputmode': 'tel',
      'placeholder': 'e.g. 0241234567 or +233241234567',
      'maxlength': 15,
    }),
  )
  consent = forms.BooleanField(
      required=True,
      label='I agree that the class participation team may store these details '
            'for class administration and contact me about participation.',
  )
  website = forms.CharField(required=False, widget=forms.HiddenInput)

  def clean_full_name(self):
    full_name = ' '.join(self.cleaned_data['full_name'].split())
    if len(full_name) < 2:
      raise forms.ValidationError('Enter your full name.')
    return full_name

  def clean_index_number(self):
    index_number = normalize_index_number(self.cleaned_data['index_number'])
    if Student.objects.filter(index_number_hash=hash_index_number(index_number)).exists():
      raise ValidationError('This student index number is already registered.')
    return index_number

  def clean_phone_number(self):
    phone_number = self.cleaned_data['phone_number'].strip()
    normalized = re.sub(r'[\s().-]', '', phone_number)
    if not re.fullmatch(r'\+?\d{7,15}', normalized):
      raise forms.ValidationError(
          'Enter a valid phone number using 7 to 15 digits, optionally starting with +.'
      )
    existing_numbers = Student.objects.exclude(phone_number='').values_list(
        'phone_number', flat=True
    )
    for existing_number in existing_numbers:
      existing_normalized = re.sub(r'[\s().-]', '', existing_number)
      if existing_normalized == normalized:
        raise ValidationError(
            'This phone number is already registered. Check the number or contact the class representative.'
        )
    return normalized

  def save(self):
    student = Student(
        full_name=self.cleaned_data['full_name'],
        phone_number=self.cleaned_data['phone_number'],
    )
    student.index_number = self.cleaned_data['index_number']
    return student