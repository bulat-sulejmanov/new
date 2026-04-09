import os

from django.conf import settings
from django.db import migrations


def _get_user_model(apps):
    app_label, model_name = settings.AUTH_USER_MODEL.split('.')
    return apps.get_model(app_label, model_name)


def _get_password(env_key, fallback):
    # Allow overriding default passwords from environment during first deploy.
    return os.getenv(env_key, fallback)


def seed_default_users(apps, schema_editor):
    user_model = _get_user_model(apps)
    group_model = apps.get_model('auth', 'Group')

    role_groups = {
        'admin': group_model.objects.get_or_create(name='Администратор')[0],
        'snab': group_model.objects.get_or_create(name='Снабженец')[0],
        'skidder': group_model.objects.get_or_create(name='Кладовщик')[0],
        'user': group_model.objects.get_or_create(name='Пользователь')[0],
    }

    users_config = [
        {
            'username': 'admin',
            'email': 'admin@tatneft.tn',
            'first_name': 'Администратор',
            'is_staff': True,
            'is_superuser': True,
            'password': _get_password('SEED_ADMIN_PASSWORD', 'admin123'),
            'group_key': 'admin',
        },
        {
            'username': 'snab',
            'email': 'snab@tatneft.tn',
            'first_name': 'Иванов А.П.',
            'is_staff': True,
            'is_superuser': False,
            'password': _get_password('SEED_SNAB_PASSWORD', 'snab123'),
            'group_key': 'snab',
        },
        {
            'username': 'skidder',
            'email': 'sklad@tatneft.tn',
            'first_name': 'Петров В.С.',
            'is_staff': True,
            'is_superuser': False,
            'password': _get_password('SEED_SKIDDER_PASSWORD', 'skidder123'),
            'group_key': 'skidder',
        },
        {
            'username': 'user',
            'email': 'user@mail.ru',
            'first_name': 'Сидоров М.И.',
            'is_staff': False,
            'is_superuser': False,
            'password': _get_password('SEED_USER_PASSWORD', 'user123'),
            'group_key': 'user',
        },
    ]

    for cfg in users_config:
        username = cfg['username']
        user = user_model.objects.filter(username=username).first()
        created = user is None

        if created:
            user = user_model(username=username)

        user.email = cfg['email']
        if hasattr(user, 'first_name'):
            user.first_name = cfg['first_name']
        user.is_staff = cfg['is_staff']
        user.is_superuser = cfg['is_superuser']
        if hasattr(user, 'is_active'):
            user.is_active = True

        if created:
            user.set_password(cfg['password'])

        user.save()

        group = role_groups[cfg['group_key']]
        if group not in user.groups.all():
            user.groups.add(group)


def noop_reverse(apps, schema_editor):
    # Keep created users and roles on reverse to avoid data loss.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('warehouse', '0013_rename_warehouse_r_supply__status_idx_warehouse_r_supply__34cd63_idx_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_default_users, noop_reverse),
    ]
