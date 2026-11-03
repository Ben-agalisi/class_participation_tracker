from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('participation', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='student',
            name='phone_number',
            field=models.CharField(
                default='',
                help_text='Format: 0241234567',
                max_length=15,
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='student',
            name='full_name',
            field=models.CharField(max_length=150),
        ),
    ]