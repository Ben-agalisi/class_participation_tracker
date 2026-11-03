import base64
import hashlib
import hmac
import os

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def normalize_index_number(value):
  return ' '.join(value.strip().upper().split())


def _master_key():
  configured_key = os.environ.get('INDEX_ENCRYPTION_KEY')
  if configured_key:
    try:
      decoded_key = base64.urlsafe_b64decode(configured_key.encode('ascii'))
    except (ValueError, UnicodeEncodeError) as error:
      raise ImproperlyConfigured(
          'INDEX_ENCRYPTION_KEY must be a URL-safe base64 Fernet key.'
      ) from error
    if len(decoded_key) != 32:
      raise ImproperlyConfigured(
          'INDEX_ENCRYPTION_KEY must decode to exactly 32 bytes.'
      )
    return configured_key.encode('ascii')

  deployment_debug = os.environ.get('DJANGO_DEBUG', 'true').lower() in {
      '1', 'true', 'yes'
  }
  if not deployment_debug:
    raise ImproperlyConfigured(
        'Set INDEX_ENCRYPTION_KEY before production startup or migrations.'
    )
  return base64.urlsafe_b64encode(
      hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).digest()
  )


def _purpose_key(purpose):
  master_key = base64.urlsafe_b64decode(_master_key())
  return hmac.new(
      master_key,
      f'class-participation:{purpose}'.encode('utf-8'),
      hashlib.sha256,
  ).digest()


def hash_index_number(value):
  normalized = normalize_index_number(value)
  return hmac.new(
      _purpose_key('index-digest'),
      normalized.encode('utf-8'),
      hashlib.sha256,
  ).hexdigest()


def index_number_last_four(value):
  digits = ''.join(character for character in value if character.isdigit())
  return digits[-4:] if len(digits) >= 4 else ''


def hash_index_number_last_four(value):
  suffix = index_number_last_four(value)
  if not suffix:
    return ''
  return hmac.new(
      _purpose_key('index-suffix-digest'),
      suffix.encode('utf-8'),
      hashlib.sha256,
  ).hexdigest()


def encrypt_index_number(value):
  key = base64.urlsafe_b64encode(_purpose_key('index-encryption'))
  return Fernet(key).encrypt(normalize_index_number(value).encode('utf-8')).decode('ascii')


def decrypt_index_number(value):
  if not value:
    return ''
  key = base64.urlsafe_b64encode(_purpose_key('index-encryption'))
  return Fernet(key).decrypt(value.encode('ascii')).decode('utf-8')