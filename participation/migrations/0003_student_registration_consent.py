from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('participation', '0002_student_phone_number_alter_student_full_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='student',
            name='registration_consent',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='student',
            name='registration_consent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]