from django.db import migrations
from django.contrib.auth.hashers import make_password


def create_owner(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    if not User.objects.filter(username='Chinnytalker').exists():
        User.objects.create(
            username='Chinnytalker',
            email='nwachukwuclinton2@gmail.com',
            password=make_password('Chinny200'),
            is_superuser=True,
            is_staff=True,
            is_active=True,
        )


def remove_owner(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(username='Chinnytalker').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_add_is_agent'),
    ]

    operations = [
        migrations.RunPython(create_owner, reverse_code=remove_owner),
    ]
