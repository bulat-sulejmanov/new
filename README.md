# «Татнефтеснаб» — Django

Автоматизация процессов склада и закупок.

## Быстрый старт

### 1. Создать виртуальную среду
```bash
python -m venv .venv
```

### 2. Установить зависимости
- Windows PowerShell:
  ```powershell
  .\.venv\Scripts\Activate.ps1
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
  ```
- Linux/Mac:
  ```bash
  source .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
  ```

### 3. Настроить переменные окружения
Скопируйте `.env.example` в `.env` и заполните параметры БД.

### 4. Запуск
```bash
python manage.py migrate
python manage.py runserver
```

## Перенос SQLite -> PostgreSQL
Подробная инструкция: `docs/postgresql_migration.md`

Короткая схема:
1. Снять дамп из SQLite в `data/current_sqlite_data.json`
2. Переключить `.env` на PostgreSQL
3. Выполнить `python manage.py migrate --noinput`
4. Выполнить `python manage.py loaddata data/current_sqlite_data.json`

## Развертывание на Render
1. Создайте web-сервис в Render с типом `Python`.
2. Укажите ветку `main`.
3. Установите Python 3.13 для сервиса Render:
   - через Dashboard: переменная окружения `PYTHON_VERSION=3.13`
   - или добавьте в корень репозитория файл `.python-version` со строкой:
     ```text
     3.13
     ```
4. Используйте команду сборки:
   ```bash
   pip install -r requirements.txt && python manage.py collectstatic --noinput
   ```
5. Используйте команду запуска:
   ```bash
   gunicorn tehsnab_warehouse.wsgi:application --bind 0.0.0.0:${PORT}
   ```
6. В Render задайте переменные окружения:
   - `DJANGO_ENV=production`
   - `DJANGO_DEBUG=False`
   - `DJANGO_SECRET_KEY` (секретный ключ)
   - `DJANGO_ALLOWED_HOSTS=.onrender.com` или конкретный домен
   - `CSRF_TRUSTED_ORIGINS=https://<your-app>.onrender.com`
   - `DATABASE_URL` (PostgreSQL)

Файл конфигурации Render: `render.yaml`

После первого запуска миграций автоматически создаются роли и учетные записи:
- `admin` / `admin123` (администратор)
- `snab` / `snab123` (снабженец)
- `skidder` / `skidder123` (кладовщик)
- `user` / `user123` (пользователь)

Рекомендуется сразу сменить пароли. При необходимости можно задать свои пароли
до первого запуска миграций через переменные `SEED_ADMIN_PASSWORD`,
`SEED_SNAB_PASSWORD`, `SEED_SKIDDER_PASSWORD`, `SEED_USER_PASSWORD`.

## Что не переносить между компьютерами
- `.venv/`
- локальные кеши Python

На новом компьютере виртуальную среду нужно создавать заново.
