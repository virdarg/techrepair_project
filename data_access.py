"""Data Access: схема SQLite, запросы и транзакционные процедуры приложения."""
import hashlib
import hmac
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
DB_PATH = Path(__file__).with_name("techrepair_app.db")
TRIGGERS_PATH = Path(__file__).with_name("techrepair_triggers.sql")

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE CHECK(length(username) BETWEEN 3 AND 30),
 password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('admin','user')),
 created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS tech_types (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS techs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 type_id INTEGER NOT NULL REFERENCES tech_types(id) ON DELETE RESTRICT,
 model TEXT NOT NULL CHECK(length(trim(model)) BETWEEN 2 AND 80), actor_id INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')), UNIQUE(owner_id,type_id,model));
CREATE TABLE IF NOT EXISTS specialists (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
 is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)));
CREATE TABLE IF NOT EXISTS services (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '',
 price REAL NOT NULL CHECK(price>=0), duration_minutes INTEGER NOT NULL CHECK(duration_minutes BETWEEN 10 AND 600),
 is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)));
CREATE TABLE IF NOT EXISTS appointments (
 id INTEGER PRIMARY KEY AUTOINCREMENT, tech_id INTEGER NOT NULL REFERENCES techs(id) ON DELETE RESTRICT,
 specialist_id INTEGER NOT NULL REFERENCES specialists(id) ON DELETE RESTRICT, start_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','cancelled','completed')),
 notes TEXT NOT NULL DEFAULT '', actor_id INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS appointment_services (
 appointment_id INTEGER NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
 service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE RESTRICT,
 price_at_booking REAL NOT NULL CHECK(price_at_booking>=0), PRIMARY KEY(appointment_id,service_id));
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT, table_name TEXT NOT NULL,
 operation TEXT NOT NULL CHECK(operation IN ('INSERT','UPDATE','DELETE')), data TEXT NOT NULL,
 username TEXT NOT NULL DEFAULT 'SYSTEM', changed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE INDEX IF NOT EXISTS idx_appointments_start ON appointments(start_at);
CREATE INDEX IF NOT EXISTS idx_appointments_specialist_time ON appointments(specialist_id,start_at);
CREATE INDEX IF NOT EXISTS idx_techs_owner ON techs(owner_id);
CREATE INDEX IF NOT EXISTS idx_audit_changed_at ON audit_log(changed_at);
CREATE VIEW IF NOT EXISTS v_appointment_details AS
 SELECT a.id,t.owner_id,u.username,a.tech_id,tt.name AS tech_type,t.model,a.specialist_id,sp.name AS specialist_name,
 a.start_at,a.status,a.notes,COALESCE(group_concat(s.name,', '),'') AS service_names,
 COALESCE(SUM(aps.price_at_booking),0) AS total_price
 FROM appointments a JOIN techs t ON t.id=a.tech_id JOIN users u ON u.id=t.owner_id
 JOIN tech_types tt ON tt.id=t.type_id JOIN specialists sp ON sp.id=a.specialist_id
 LEFT JOIN appointment_services aps ON aps.appointment_id=a.id LEFT JOIN services s ON s.id=aps.service_id
 GROUP BY a.id;
CREATE VIEW IF NOT EXISTS v_service_report AS
 SELECT s.id AS service_id,s.name AS service_name,COUNT(DISTINCT a.id) AS appointment_count,
 COALESCE(SUM(CASE WHEN a.id IS NOT NULL THEN aps.price_at_booking ELSE 0 END),0) AS revenue,
 AVG(s.price) AS average_price,AVG(s.duration_minutes) AS average_duration_minutes
 FROM services s LEFT JOIN appointment_services aps ON aps.service_id=s.id
 LEFT JOIN appointments a ON a.id=aps.appointment_id AND a.status<>'cancelled' GROUP BY s.id,s.name;
"""
# Критические триггеры встроены в модуль: приложение не зависит от наличия
# отдельного SQL-файла при запуске из архива или IDE.
TRIGGER_SQL = r"""
-- Назначение: бизнес-ограничения и аудит изменений таблиц appointments и techs.
-- SQLite-эквивалент THROW: RAISE(ABORT, 'понятная ошибка'); операция откатывается.
-- Автор: OpenAI; дата: 2026-10-29.

DROP TRIGGER IF EXISTS trg_appointments_validate_insert; CREATE TRIGGER trg_appointments_validate_insert
BEFORE INSERT ON appointments
BEGIN
    SELECT CASE WHEN datetime(NEW.start_at) IS NULL
        OR strftime('%Y-%m-%d %H:%M', datetime(NEW.start_at)) <> NEW.start_at
        THEN RAISE(ABORT, 'Неверный формат даты и времени') END;
    SELECT CASE WHEN NEW.status = 'scheduled'
        AND datetime(NEW.start_at) <= datetime('now','localtime')
        THEN RAISE(ABORT, 'Дата записи должна быть в будущем') END;
    SELECT CASE WHEN NEW.status = 'scheduled' AND EXISTS (
        SELECT 1 FROM appointments a WHERE a.specialist_id=NEW.specialist_id
          AND a.start_at=NEW.start_at AND a.status='scheduled'
    ) THEN RAISE(ABORT, 'Специалист уже занят в это время') END;
END;

DROP TRIGGER IF EXISTS trg_appointments_validate_update; CREATE TRIGGER trg_appointments_validate_update
BEFORE UPDATE OF specialist_id, start_at, status ON appointments
BEGIN
    SELECT CASE WHEN datetime(NEW.start_at) IS NULL
        OR strftime('%Y-%m-%d %H:%M', datetime(NEW.start_at)) <> NEW.start_at
        THEN RAISE(ABORT, 'Неверный формат даты и времени') END;
    SELECT CASE WHEN NEW.status = 'scheduled'
        AND datetime(NEW.start_at) <= datetime('now','localtime')
        THEN RAISE(ABORT, 'Дата записи должна быть в будущем') END;
    SELECT CASE WHEN NEW.status = 'scheduled' AND EXISTS (
        SELECT 1 FROM appointments a WHERE a.specialist_id=NEW.specialist_id
          AND a.start_at=NEW.start_at AND a.status='scheduled' AND a.id<>NEW.id
    ) THEN RAISE(ABORT, 'Специалист уже занят в это время') END;
END;
-- AFTER-триггеры аудита корректно обрабатывают и многострочные INSERT/UPDATE/DELETE:
-- SQLite запускает их отдельно для каждой затронутой строки.
DROP TRIGGER IF EXISTS trg_appointments_audit_insert; CREATE TRIGGER trg_appointments_audit_insert AFTER INSERT ON appointments BEGIN
    INSERT INTO audit_log(table_name,operation,data,username)
    VALUES('appointments','INSERT', 'id='||NEW.id||'; tech_id='||NEW.tech_id||
        '; specialist_id='||NEW.specialist_id||'; start_at='||NEW.start_at||'; status='||NEW.status,
        COALESCE((SELECT username FROM users WHERE id=NEW.actor_id),'SYSTEM'));
END;
DROP TRIGGER IF EXISTS trg_appointments_audit_update; CREATE TRIGGER trg_appointments_audit_update AFTER UPDATE ON appointments BEGIN
    INSERT INTO audit_log(table_name,operation,data,username)
    VALUES('appointments','UPDATE', 'id='||NEW.id||'; status='||OLD.status||' -> '||NEW.status||
        '; start_at='||OLD.start_at||' -> '||NEW.start_at,
        COALESCE((SELECT username FROM users WHERE id=NEW.actor_id),'SYSTEM'));
END;
DROP TRIGGER IF EXISTS trg_appointments_audit_delete; CREATE TRIGGER trg_appointments_audit_delete AFTER DELETE ON appointments BEGIN
    INSERT INTO audit_log(table_name,operation,data,username)
    VALUES('appointments','DELETE', 'id='||OLD.id||'; start_at='||OLD.start_at||'; status='||OLD.status,
        COALESCE((SELECT username FROM users WHERE id=OLD.actor_id),'SYSTEM'));
END;

DROP TRIGGER IF EXISTS trg_techs_audit_insert; CREATE TRIGGER trg_techs_audit_insert AFTER INSERT ON techs BEGIN
    INSERT INTO audit_log(table_name,operation,data,username)
    VALUES('techs','INSERT','id='||NEW.id||'; owner_id='||NEW.owner_id||'; type_id='||NEW.type_id||'; model='||NEW.model,
        COALESCE((SELECT username FROM users WHERE id=NEW.actor_id),'SYSTEM'));
END;
DROP TRIGGER IF EXISTS trg_techs_audit_update; CREATE TRIGGER trg_techs_audit_update AFTER UPDATE ON techs BEGIN
    INSERT INTO audit_log(table_name,operation,data,username)
    VALUES('techs','UPDATE','id='||NEW.id||'; model='||OLD.model||' -> '||NEW.model,
        COALESCE((SELECT username FROM users WHERE id=NEW.actor_id),'SYSTEM'));
END;
DROP TRIGGER IF EXISTS trg_techs_audit_delete; CREATE TRIGGER trg_techs_audit_delete AFTER DELETE ON techs BEGIN
    INSERT INTO audit_log(table_name,operation,data,username)
    VALUES('techs','DELETE','id='||OLD.id||'; model='||OLD.model,
        COALESCE((SELECT username FROM users WHERE id=OLD.actor_id),'SYSTEM'));
END;

-- INSTEAD OF не нужен: запись ведётся в реальные таблицы, а представления только читаются.

"""

def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 160_000)
    return salt.hex() + "$" + digest.hex()

def verify_password(password, stored_hash):
    try:
        salt_hex, digest_hex = stored_hash.split("$", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 160_000)
        return hmac.compare_digest(actual.hex(), digest_hex)
    except (ValueError, TypeError):
        return False

def _is_valid_datetime(value):
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M")
        return 1
    except (TypeError, ValueError):
        return 0
def _duration_hours(minutes):
    return round(float(minutes) / 60, 2) if minutes is not None else 0

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.create_function("fn_is_valid_datetime", 1, _is_valid_datetime, deterministic=True)
    conn.create_function("fn_duration_hours", 1, _duration_hours, deterministic=True)
    return conn

@contextmanager
def _transaction():
    """Единая замена TRY/CATCH: при любом исключении выполняется ROLLBACK."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
def init_db():
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        # Устанавливаем триггеры из встроенного SQL, чтобы ограничения и аудит
        # работали даже если techrepair_triggers.sql не был скопирован отдельно.
        conn.executescript(TRIGGER_SQL)
        if not conn.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
            conn.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                         ("admin", hash_password("admin123"), "admin"))
        if not conn.execute("SELECT 1 FROM users WHERE username='user'").fetchone():
            conn.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                         ("user", hash_password("user123"), "user"))
        conn.executemany("INSERT OR IGNORE INTO tech_types(name) VALUES(?)", [
            ("Мобильное устройство",), ("Персональный компьютер",), ("Ноутбук",),
            ("Игровая приставка",), ("Иное устройство",)])
        conn.executemany("INSERT OR IGNORE INTO specialists(name) VALUES(?)", [
            ("Алексей Смирнов",), ("Мария Волкова",), ("Илья Петров",)])
        conn.executemany("INSERT OR IGNORE INTO services(name,description,price,duration_minutes) VALUES(?,?,?,?)", [
            ("Ремонт", "Диагностика и ремонт неисправности", 1500, 120),
            ("Чистка", "Чистка устройства от пыли и загрязнений", 700, 60),
            ("Диагностика", "Проверка устройства и поиск неисправности", 500, 30)])
        conn.commit()
    finally:
        conn.close()

# Процедуры выборки с необязательными параметрами фильтра.
def _rows(sql, params=()):
    conn = get_connection()
    try: return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally: conn.close()
def _one(sql, params=()):
    conn = get_connection()
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally: conn.close()

def proc_users_get_by_username(username):
    return _one("SELECT * FROM users WHERE username=?", (username,))
def proc_tech_types_select():
    return _rows("SELECT id,name FROM tech_types ORDER BY id")
def proc_techs_select(owner_id=None):
    return _rows("""SELECT t.id,t.owner_id,u.username,t.type_id,tt.name AS type_name,t.model
        FROM techs t JOIN users u ON u.id=t.owner_id JOIN tech_types tt ON tt.id=t.type_id
        WHERE (? IS NULL OR t.owner_id=?) ORDER BY t.id DESC""", (owner_id, owner_id))

def proc_specialists_select(active_only=True):
    return _rows("SELECT id,name FROM specialists WHERE (?=0 OR is_active=1) ORDER BY name", (int(active_only),))
def proc_services_select(active_only=True):
    return _rows("SELECT id,name,description,price,duration_minutes FROM services WHERE (?=0 OR is_active=1) ORDER BY id", (int(active_only),))
def proc_appointments_select(owner_id=None, status="all", date_from=None, date_to=None):
    return _rows("""SELECT * FROM v_appointment_details WHERE (? IS NULL OR owner_id=?) AND (?='all' OR status=?)
        AND (? IS NULL OR start_at>=?) AND (? IS NULL OR start_at<=?) ORDER BY start_at DESC""",
        (owner_id, owner_id, status, status, date_from, date_from, date_to, date_to))

def proc_audit_select(limit=200, table_name=None):
    limit = max(1, min(int(limit), 1000))
    return _rows("""SELECT id,table_name,operation,data,username,changed_at FROM audit_log
        WHERE (? IS NULL OR table_name=?) ORDER BY id DESC LIMIT ?""", (table_name, table_name, limit))
def proc_report_services(date_from=None, date_to=None):
    return _rows("""SELECT s.name AS service_name,COUNT(DISTINCT a.id) AS appointments,
        COALESCE(SUM(CASE WHEN a.id IS NOT NULL THEN aps.price_at_booking ELSE 0 END),0) AS revenue,
        ROUND(AVG(fn_duration_hours(s.duration_minutes)),2) AS avg_duration_hours
        FROM services s LEFT JOIN appointment_services aps ON aps.service_id=s.id
        LEFT JOIN appointments a ON a.id=aps.appointment_id AND a.status<>'cancelled'
          AND (? IS NULL OR a.start_at>=?) AND (? IS NULL OR a.start_at<=?)
        GROUP BY s.id,s.name ORDER BY revenue DESC,s.name""", (date_from,date_from,date_to,date_to))
def proc_report_monthly(date_from=None, date_to=None):
    return _rows("""SELECT substr(a.start_at,1,7) AS month,COUNT(DISTINCT a.id) AS appointments,
        COALESCE(SUM(aps.price_at_booking),0) AS revenue,ROUND(AVG(aps.price_at_booking),2) AS avg_service_price
        FROM appointments a LEFT JOIN appointment_services aps ON aps.appointment_id=a.id
        WHERE a.status<>'cancelled' AND (? IS NULL OR a.start_at>=?) AND (? IS NULL OR a.start_at<=?)
        GROUP BY substr(a.start_at,1,7) ORDER BY month DESC""", (date_from,date_from,date_to,date_to))

# Табличные функции SQLite не поддерживает: эти параметризованные функции возвращают набор строк.
def tvf_user_appointments(owner_id=None, status="all", date_from=None, date_to=None):
    return proc_appointments_select(owner_id, status, date_from, date_to)
def tvf_service_summary(date_from=None, date_to=None):
    return proc_report_services(date_from, date_to)

# Процедуры модификации. Все операции выполняются транзакционно, с откатом при ошибке.
def proc_users_insert(username, password_hash, role="user"):
    """Назначение: регистрация. Параметры: username, password_hash, role. Автор: OpenAI; 2026-10-29."""
    if not username or not password_hash or role != "user":
        raise ValueError("Некорректные данные пользователя")
    with _transaction() as conn:
        cur = conn.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                           (username, password_hash, role))
        return cur.lastrowid  # аналог OUTPUT-параметра

def proc_techs_insert(owner_id, type_id, model, actor_id):
    """Назначение: добавить технику. Параметры: owner_id, type_id, model, actor_id. Автор: OpenAI; 2026-10-29."""
    if not all((owner_id, type_id, actor_id)) or not model or not 2 <= len(model.strip()) <= 80:
        raise ValueError("Укажите тип техники и название длиной 2–80 символов")
    with _transaction() as conn:
        cur = conn.execute("INSERT INTO techs(owner_id,type_id,model,actor_id) VALUES(?,?,?,?)",
                           (owner_id, type_id, model.strip(), actor_id))
        return cur.lastrowid
def proc_appointments_insert(owner_id, tech_id, specialist_id, start_at, service_id, actor_id, notes=""):
    """Назначение: атомарно создать запись и услуги. Параметры: поля записи. Автор: OpenAI; 2026-10-29."""
    with _transaction() as conn:
        if not conn.execute("SELECT fn_is_valid_datetime(?)", (start_at,)).fetchone()[0]:
            raise ValueError("Дата должна быть в формате ГГГГ-ММ-ДД ЧЧ:ММ")
        tech = conn.execute("SELECT owner_id FROM techs WHERE id=?", (tech_id,)).fetchone()
        service = conn.execute("SELECT price FROM services WHERE id=? AND is_active=1", (service_id,)).fetchone()
        specialist = conn.execute("SELECT 1 FROM specialists WHERE id=? AND is_active=1", (specialist_id,)).fetchone()
        if not tech or tech["owner_id"] != owner_id:
            raise ValueError("Техника не найдена или владелец не совпадает")
        if not service or not specialist:
            raise ValueError("Выберите доступную услугу и специалиста")
        cur = conn.execute("""INSERT INTO appointments(tech_id,specialist_id,start_at,notes,actor_id)
            VALUES(?,?,?,?,?)""", (tech_id, specialist_id, start_at, notes.strip(), actor_id))
        appointment_id = cur.lastrowid
        conn.execute("INSERT INTO appointment_services(appointment_id,service_id,price_at_booking) VALUES(?,?,?)",
                     (appointment_id, service_id, service["price"]))
        return appointment_id

def proc_appointments_update_status(appointment_id, status, actor_id):
    """Назначение: сменить статус записи. Параметры: appointment_id, status, actor_id. Автор: OpenAI; 2026-10-29."""
    if status not in ("scheduled", "cancelled", "completed"):
        raise ValueError("Недопустимый статус записи")
    with _transaction() as conn:
        cur = conn.execute("UPDATE appointments SET status=?,actor_id=? WHERE id=?",
                           (status, actor_id, appointment_id))
        if cur.rowcount != 1:
            raise ValueError("Запись не найдена")
        return cur.rowcount

def proc_appointments_delete(appointment_id):
    """Назначение: удалить запись (административная операция). Параметр: appointment_id. Автор: OpenAI; 2026-10-29."""
    with _transaction() as conn:
        cur = conn.execute("DELETE FROM appointments WHERE id=?", (appointment_id,))
        if cur.rowcount != 1:
            raise ValueError("Запись не найдена")
        return cur.rowcount
def proc_specialists_insert(name):
    """Назначение: добавить специалиста. Параметр: name. Автор: OpenAI; 2026-10-29."""
    if not name or not name.strip():
        raise ValueError("Имя специалиста обязательно")
    with _transaction() as conn:
        cur = conn.execute("INSERT INTO specialists(name) VALUES(?)", (name.strip(),))
        return cur.lastrowid

def proc_services_update_price(service_id, price):
    """Назначение: изменить цену услуги. Параметры: service_id, price. Автор: OpenAI; 2026-10-29."""
    if price < 0:
        raise ValueError("Цена не может быть отрицательной")
    with _transaction() as conn:
        cur = conn.execute("UPDATE services SET price=? WHERE id=?", (price, service_id))
        if cur.rowcount != 1:
            raise ValueError("Услуга не найдена")
        return cur.rowcount
