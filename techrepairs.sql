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
