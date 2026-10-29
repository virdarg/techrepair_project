"""Модульные и интеграционные тесты. Запуск: python -m unittest discover -s tests -v."""
import sys, tempfile, unittest
from datetime import datetime, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import data_access as dal
from business_logic import AuthService, RepairService, AdminService, ValidationError, AccessDeniedError, ConflictError

class BaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = dal.DB_PATH
        dal.DB_PATH = Path(self.tmp.name) / "test.db"
        dal.init_db()
        self.auth, self.repair, self.admin = AuthService(), RepairService(), AdminService()
        self.user = self.auth.login("user", "user123")
        self.admin_user = self.auth.login("admin", "admin123")
        self.type_id = dal.proc_tech_types_select()[0]["id"]
        self.specialist_id = dal.proc_specialists_select()[0]["id"]
        self.service_id = dal.proc_services_select()[0]["id"]
        self.tech_id = self.repair.add_tech(self.user, self.type_id, "Тестовый ноутбук")
    def tearDown(self):
        dal.DB_PATH = self.old_path
        self.tmp.cleanup()
    def future_time(self, minutes=60):
        return (datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")

class TestValidationAndAuth(BaseTest):
    def test_login_success(self): self.assertEqual(self.user["role"], "user")
    def test_login_wrong_password(self):
        with self.assertRaises(ValidationError): self.auth.login("user", "wrong-password")
    def test_register_duplicate(self):
        with self.assertRaises(ValidationError): self.auth.register("user", "newpassword")
    def test_register_invalid_username(self):
        with self.assertRaises(ValidationError): self.auth.register("x", "password123")
    def test_register_valid(self): self.assertGreater(self.auth.register("test_user", "password123"), 0)
    def test_add_tech_invalid_model(self):
        with self.assertRaises(ValidationError): self.repair.add_tech(self.user, self.type_id, " ")
    def test_add_duplicate_tech(self):
        with self.assertRaises(ValidationError): self.repair.add_tech(self.user, self.type_id, "Тестовый ноутбук")

class TestAppointmentsIntegration(BaseTest):
    def test_book_appointment(self):
        aid = self.repair.book(self.user, self.tech_id, self.specialist_id, self.service_id, self.future_time(), "проверка")
        self.assertGreater(aid, 0)
        self.assertTrue(any(a["id"] == aid for a in self.repair.appointments(self.user)))
    def test_reject_bad_datetime(self):
        with self.assertRaises(ValidationError): self.repair.book(self.user, self.tech_id, self.specialist_id, self.service_id, "завтра вечером")
    def test_reject_past_datetime(self):
        past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
        with self.assertRaises(ValidationError): self.repair.book(self.user, self.tech_id, self.specialist_id, self.service_id, past)
    def test_conflicting_specialist_time_rolls_back(self):
        slot = self.future_time(90)
        self.repair.book(self.user, self.tech_id, self.specialist_id, self.service_id, slot)
        before = len(self.repair.appointments(self.user))
        with self.assertRaises(ConflictError): self.repair.book(self.user, self.tech_id, self.specialist_id, self.service_id, slot)
        self.assertEqual(len(self.repair.appointments(self.user)), before)
    def test_user_cannot_book_other_users_tech(self):
        self.auth.register("other_user", "password123")
        other = self.auth.login("other_user", "password123")
        other_tech = self.repair.add_tech(other, self.type_id, "Чужое устройство")
        with self.assertRaises(AccessDeniedError): self.repair.book(self.user, other_tech, self.specialist_id, self.service_id, self.future_time(120))
    def test_cancel_appointment(self):
        aid = self.repair.book(self.user, self.tech_id, self.specialist_id, self.service_id, self.future_time())
        self.repair.cancel(self.user, aid)
        row = next(a for a in self.repair.appointments(self.user) if a["id"] == aid)
        self.assertEqual(row["status"], "cancelled")
    def test_user_cannot_view_admin_report(self):
        with self.assertRaises(AccessDeniedError): self.admin.service_report(self.user)
    def test_admin_report_and_audit(self):
        self.repair.book(self.user, self.tech_id, self.specialist_id, self.service_id, self.future_time())
        self.assertTrue(self.admin.service_report(self.admin_user))
        self.assertIsInstance(self.admin.audit(self.admin_user), list)

class TestDatabaseConstraints(BaseTest):
    def test_foreign_keys_enabled(self):
        conn = dal.get_connection()
        try: self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        finally: conn.close()
    def test_required_views_exist(self):
        conn = dal.get_connection()
        try:
            views = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")}
            self.assertTrue({"v_appointment_details", "v_service_report"}.issubset(views))
        finally: conn.close()
    def test_audit_created_for_tech_insert(self):
        conn = dal.get_connection()
        try:
            count = conn.execute("SELECT COUNT(*) FROM audit_log WHERE table_name='techs' AND operation='INSERT'").fetchone()[0]
            self.assertGreaterEqual(count, 1)
        finally: conn.close()

if __name__ == "__main__": unittest.main()
