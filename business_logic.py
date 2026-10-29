"""Business Logic: валидация, роли и правила приложения."""
import sqlite3
from datetime import datetime
import data_access as dal

class ValidationError(Exception): pass
class AccessDeniedError(Exception): pass
class ConflictError(Exception): pass


class AuthService:
    def login(self, username, password):
        if not username.strip() or not password:
            raise ValidationError("Введите логин и пароль")
        user = dal.proc_users_get_by_username(username.strip())
        if not user or not dal.verify_password(password, user["password_hash"]):
            raise ValidationError("Неверный логин или пароль")
        user.pop("password_hash", None)
        return user
    def register(self, username, password):
        username = username.strip()
        if not 3 <= len(username) <= 30 or not all(c.isalnum() or c == "_" for c in username):
            raise ValidationError("Логин: 3–30 символов, только буквы, цифры и _")
        if len(password) < 8:
            raise ValidationError("Пароль должен содержать не менее 8 символов")
        try:
            return dal.proc_users_insert(username, dal.hash_password(password), "user")
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValidationError("Такой логин уже существует") from exc
            raise ValidationError(f"Не удалось создать пользователя: {exc}") from exc


class RepairService:
    def add_tech(self, user, type_id, model):
        model = model.strip()
        if not type_id or not 2 <= len(model) <= 80:
            raise ValidationError("Выберите тип устройства и введите название (2–80 символов)")
        try:
            return dal.proc_techs_insert(user["id"], type_id, model, user["id"])
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValidationError("Такая техника уже добавлена") from exc
            raise ValidationError(f"Не удалось добавить технику: {exc}") from exc
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

    def book(self, user, tech_id, specialist_id, service_id, start_at, notes=""):
        try:
            parsed = datetime.strptime(start_at.strip(), "%Y-%m-%d %H:%M")
        except ValueError as exc:
            raise ValidationError("Введите дату как ГГГГ-ММ-ДД ЧЧ:ММ") from exc
        if parsed <= datetime.now().replace(second=0, microsecond=0):
            raise ValidationError("Дата и время должны быть в будущем")
        if len(notes.strip()) > 300:
            raise ValidationError("Комментарий не должен превышать 300 символов")
        techs = dal.proc_techs_select(None if user["role"] == "admin" else user["id"])
        tech = next((t for t in techs if t["id"] == tech_id), None)
        if not tech:
            raise AccessDeniedError("Эта техника недоступна для записи")
        try:
            return dal.proc_appointments_insert(
                tech["owner_id"], tech_id, specialist_id, start_at.strip(),
                service_id, user["id"], notes)
        except sqlite3.IntegrityError as exc:
            text = str(exc)
            if "занят" in text.lower():
                raise ConflictError(text) from exc
            if "будущ" in text.lower() or "формат" in text.lower():
                raise ValidationError(text) from exc
            raise ValidationError(f"Не удалось создать запись: {text}") from exc
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

    def appointments(self, user, status="all"):
        owner_id = None if user["role"] == "admin" else user["id"]
        return dal.tvf_user_appointments(owner_id, status)

    def cancel(self, user, appointment_id):
        owner_id = None if user["role"] == "admin" else user["id"]
        appointment = next((a for a in dal.tvf_user_appointments(owner_id)
                            if a["id"] == appointment_id), None)
        if not appointment:
            raise AccessDeniedError("Запись не найдена или у вас нет прав на её изменение")
        if appointment["status"] != "scheduled":
            raise ValidationError("Можно отменить только запланированную запись")
        try:
            return dal.proc_appointments_update_status(appointment_id, "cancelled", user["id"])
        except (sqlite3.Error, ValueError) as exc:
            raise ValidationError(f"Не удалось отменить запись: {exc}") from exc

class AdminService:
    def _check(self, user):
        if user.get("role") != "admin":
            raise AccessDeniedError("Раздел доступен только администратору")

    def service_report(self, user):
        self._check(user)
        return dal.tvf_service_summary()

    def monthly_report(self, user):
        self._check(user)
        return dal.proc_report_monthly()
    def audit(self, user):
        self._check(user)
        return dal.proc_audit_select(300)
