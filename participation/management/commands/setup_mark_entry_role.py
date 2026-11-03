from django.contrib.auth.models import Group, Permission
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
  help = 'Create or refresh the limited Mark Entry Staff group.'

  def handle(self, *args, **options):
    mark_entry_codenames = (
        'view_student',
        'view_participationlog',
        'award_marks',
    )
    mark_entry_permissions = list(
        Permission.objects.filter(
            content_type__app_label='participation',
            codename__in=mark_entry_codenames,
        )
    )
    found_codenames = {permission.codename for permission in mark_entry_permissions}
    missing = set(mark_entry_codenames) - found_codenames
    if missing:
      raise CommandError(
          'Required permissions are missing. Run migrations first: '
          + ', '.join(sorted(missing))
      )

    mark_entry_group, created = Group.objects.get_or_create(
        name=settings.MARK_ENTRY_GROUP_NAME
    )
    mark_entry_group.permissions.set(mark_entry_permissions)
    action = 'Created' if created else 'Updated'
    self.stdout.write(
        self.style.SUCCESS(f'{action} {settings.MARK_ENTRY_GROUP_NAME} role.')
    )
    self.stdout.write(
        'This role can view students and participation logs and use the validated '
        'marks workflow. It cannot directly create logs or administer accounts.'
    )
