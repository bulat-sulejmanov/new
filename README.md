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

## Что не переносить между компьютерами
- `.venv/`
- локальные кеши Python

На новом компьютере виртуальную среду нужно создавать заново.
