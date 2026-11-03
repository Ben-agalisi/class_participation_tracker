from django.db import migrations, models


def encrypt_existing_index_numbers(apps, schema_editor):
  from participation.index_security import encrypt_index_number, hash_index_number

  Student = apps.get_model('participation', 'Student')
  for student in Student.objects.all().iterator():
    student.index_number_encrypted = encrypt_index_number(student.index_number)
    student.index_number_hash = hash_index_number(student.index_number)
    student.save(update_fields=['index_number_encrypted', 'index_number_hash'])


def restore_plain_index_numbers(apps, schema_editor):
  from participation.index_security import decrypt_index_number

  Student = apps.get_model('participation', 'Student')
  for student in Student.objects.all().iterator():
    student.index_number = decrypt_index_number(student.index_number_encrypted)
    student.save(update_fields=['index_number'])


class Migration(migrations.Migration):

  dependencies = [
      ('participation', '0003_student_registration_consent'),
  ]

  operations = [
      migrations.AddField(
          model_name='student',
          name='index_number_encrypted',
          field=models.TextField(null=True),
      ),
      migrations.AddField(
          model_name='student',
          name='index_number_hash',
          field=models.CharField(max_length=64, null=True, unique=True),
      ),
      migrations.RunPython(
          encrypt_existing_index_numbers,
          restore_plain_index_numbers,
      ),
      migrations.AlterField(
          model_name='student',
          name='index_number_encrypted',
          field=models.TextField(),
      ),
      migrations.AlterField(
          model_name='student',
          name='index_number_hash',
          field=models.CharField(max_length=64, unique=True),
      ),
      migrations.RemoveField(
          model_name='student',
          name='index_number',
      ),
  ]