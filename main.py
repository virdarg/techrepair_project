"""Presentation: Tkinter-интерфейс приложения учёта ремонта техники."""
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta
import data_access as dal
from business_logic import AuthService, RepairService, AdminService, ValidationError, AccessDeniedError, ConflictError

class TechRepairApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Сервисный центр — запись на ремонт")
        self.root.geometry("1050x680")
        self.root.minsize(850, 560)
        self.auth = AuthService()
        self.repairs = RepairService()
        self.admin = AdminService()
        self.user = None
        self.show_login()

    def clear(self):
        for child in self.root.winfo_children():
            child.destroy()

    def show_login(self):
        self.clear()
        frame = ttk.LabelFrame(self.root, text="Вход в сервисный центр", padding=22)
        frame.pack(padx=25, pady=55)
        ttk.Label(frame, text="Логин").grid(row=0, column=0, sticky="w", padx=6, pady=7)
        self.login_name = ttk.Entry(frame, width=32)
        self.login_name.grid(row=0, column=1, padx=6, pady=7)
        ttk.Label(frame, text="Пароль").grid(row=1, column=0, sticky="w", padx=6, pady=7)
        self.login_password = ttk.Entry(frame, width=32, show="●")
        self.login_password.grid(row=1, column=1, padx=6, pady=7)
        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, columnspan=2, pady=12)
        ttk.Button(buttons, text="Войти", command=self.do_login).pack(side="left", padx=5)
        ttk.Button(buttons, text="Создать аккаунт", command=self.do_register).pack(side="left", padx=5)
        ttk.Label(frame, text="Демо-вход: admin / admin123   или   user / user123").grid(
            row=3, column=0, columnspan=2, pady=(7, 0))
        self.login_password.bind("<Return>", lambda _e: self.do_login())

    def do_login(self):
        try:
            self.user = self.auth.login(self.login_name.get(), self.login_password.get())
            self.show_main()
        except ValidationError as exc:
            messagebox.showerror("Вход не выполнен", str(exc))

    def do_register(self):
        try:
            self.auth.register(self.login_name.get(), self.login_password.get())
            messagebox.showinfo("Готово", "Аккаунт создан. Теперь войдите с указанными данными.")
        except ValidationError as exc:
            messagebox.showerror("Регистрация", str(exc))
    def show_main(self):
        self.clear()
        header = ttk.Frame(self.root, padding=(10, 8))
        header.pack(fill="x")
        role_name = "администратор" if self.user["role"] == "admin" else "пользователь"
        ttk.Label(header, text=f"Пользователь: {self.user['username']} ({role_name})",
                  font=("Arial", 11, "bold")).pack(side="left")
        ttk.Button(header, text="Выйти", command=self.show_login).pack(side="right")
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.tab_book = ttk.Frame(self.notebook, padding=10)
        self.tab_techs = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_book, text="Запись на услугу")
        self.notebook.add(self.tab_techs, text="Техника")
        self.build_booking_tab()
        self.build_techs_tab()
        if self.user["role"] == "admin":
            self.tab_report = ttk.Frame(self.notebook, padding=10)
            self.tab_audit = ttk.Frame(self.notebook, padding=10)
            self.notebook.add(self.tab_report, text="Отчёты")
            self.notebook.add(self.tab_audit, text="Аудит")
            self.build_report_tab()
            self.build_audit_tab()

    def build_booking_tab(self):
        form = ttk.LabelFrame(self.tab_book, text="Новая запись", padding=9)
        form.pack(fill="x", pady=(0, 8))
        ttk.Label(form, text="Устройство").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.tech_combo = ttk.Combobox(form, state="readonly", width=34)
        self.tech_combo.grid(row=0, column=1, padx=4, pady=4)
        ttk.Label(form, text="Услуга").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        self.service_combo = ttk.Combobox(form, state="readonly", width=22)
        self.service_combo.grid(row=0, column=3, padx=4, pady=4)
        ttk.Label(form, text="Специалист").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        self.specialist_combo = ttk.Combobox(form, state="readonly", width=34)
        self.specialist_combo.grid(row=1, column=1, padx=4, pady=4)
        ttk.Label(form, text="Дата и время").grid(row=1, column=2, sticky="w", padx=4, pady=4)
        default_time = (datetime.now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        self.datetime_entry = ttk.Entry(form, width=25)
        self.datetime_entry.insert(0, default_time.strftime("%Y-%m-%d %H:%M"))
        self.datetime_entry.grid(row=1, column=3, padx=4, pady=4)
        ttk.Label(form, text="Комментарий (необязательно)").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        self.notes_entry = ttk.Entry(form, width=55)
        self.notes_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=4, pady=4)
        ttk.Button(form, text="Записаться", command=self.on_book).grid(row=2, column=3, padx=4, pady=4, sticky="ew")
        self.app_tree = ttk.Treeview(self.tab_book, columns=("id", "date", "user", "tech", "specialist", "service", "price", "status"),
                                     show="headings", height=14)
        headings = (("id", "ID", 45), ("date", "Дата и время", 135), ("user", "Владелец", 100),
                    ("tech", "Устройство", 175), ("specialist", "Специалист", 130),
                    ("service", "Услуга", 100), ("price", "Цена", 75), ("status", "Статус", 95))
        for col, label, width in headings:
            self.app_tree.heading(col, text=label)
            self.app_tree.column(col, width=width, anchor="w")
        self.app_tree.pack(fill="both", expand=True)
        ttk.Button(self.tab_book, text="Отменить выбранную запись", command=self.on_cancel).pack(anchor="e", pady=7)
        self.refresh_booking_data()

    def refresh_booking_data(self):
        techs = dal.proc_techs_select(None if self.user["role"] == "admin" else self.user["id"])
        self.tech_options = {f"{t['id']}: {t['type_name']} — {t['model']}" : t for t in techs}
        self.tech_combo["values"] = list(self.tech_options)
        if techs:
            self.tech_combo.current(0)
        services = dal.proc_services_select()
        self.service_options = {f"{s['name']} — {s['price']:.2f} руб.": s for s in services}
        self.service_combo["values"] = list(self.service_options)
        if services:
            self.service_combo.current(0)
        specialists = dal.proc_specialists_select()
        self.specialist_options = {s["name"]: s for s in specialists}
        self.specialist_combo["values"] = list(self.specialist_options)
        if specialists:
            self.specialist_combo.current(0)
        self.refresh_appointments()

    def on_book(self):
        tech = self.tech_options.get(self.tech_combo.get())
        service = self.service_options.get(self.service_combo.get())
        specialist = self.specialist_options.get(self.specialist_combo.get())
        if not all((tech, service, specialist)):
            messagebox.showwarning("Запись", "Сначала добавьте технику и выберите услугу и специалиста")
            return
        try:
            self.repairs.book(self.user, tech["id"], specialist["id"], service["id"],
                              self.datetime_entry.get(), self.notes_entry.get())
            messagebox.showinfo("Готово", "Запись создана")
            self.refresh_appointments()
        except (ValidationError, AccessDeniedError, ConflictError) as exc:
            messagebox.showerror("Не удалось записаться", str(exc))

    def refresh_appointments(self):
        for item in self.app_tree.get_children():
            self.app_tree.delete(item)
        for a in self.repairs.appointments(self.user):
            status = {"scheduled": "Запланирована", "cancelled": "Отменена", "completed": "Завершена"}.get(a["status"], a["status"])
            self.app_tree.insert("", "end", values=(a["id"], a["start_at"], a["username"],
                f"{a['tech_type']} — {a['model']}", a["specialist_name"], a["service_names"],
                f"{a['total_price']:.2f}", status))

    def on_cancel(self):
        selection = self.app_tree.selection()
        if not selection:
            messagebox.showwarning("Отмена записи", "Выберите запись в таблице")
            return
        appointment_id = int(self.app_tree.item(selection[0], "values")[0])
        try:
            self.repairs.cancel(self.user, appointment_id)
            self.refresh_appointments()
            messagebox.showinfo("Готово", "Запись отменена")
        except (ValidationError, AccessDeniedError) as exc:
            messagebox.showerror("Отмена записи", str(exc))
    def build_techs_tab(self):
        form = ttk.LabelFrame(self.tab_techs, text="Добавить свою технику", padding=10)
        form.pack(fill="x", pady=(0, 8))
        ttk.Label(form, text="Тип устройства").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        types = dal.proc_tech_types_select()
        self.type_options = {t["name"]: t for t in types}
        self.type_combo = ttk.Combobox(form, state="readonly", width=30, values=list(self.type_options))
        self.type_combo.grid(row=0, column=1, padx=5, pady=5)
        if types:
            self.type_combo.current(0)
        ttk.Label(form, text="Модель / название").grid(row=0, column=2, padx=5, pady=5, sticky="w")
        self.model_entry = ttk.Entry(form, width=30)
        self.model_entry.grid(row=0, column=3, padx=5, pady=5)
        ttk.Button(form, text="Добавить", command=self.on_add_tech).grid(row=0, column=4, padx=5, pady=5)
        columns = ("id", "owner", "type", "model")
        self.tech_tree = ttk.Treeview(self.tab_techs, columns=columns, show="headings", height=17)
        for col, title, width in (("id", "ID", 55), ("owner", "Владелец", 160), ("type", "Тип устройства", 230), ("model", "Модель / название", 350)):
            self.tech_tree.heading(col, text=title)
            self.tech_tree.column(col, width=width)
        self.tech_tree.pack(fill="both", expand=True)
        self.refresh_techs()

    def on_add_tech(self):
        kind = self.type_options.get(self.type_combo.get())
        if not kind:
            messagebox.showwarning("Техника", "Выберите тип устройства")
            return
        try:
            self.repairs.add_tech(self.user, kind["id"], self.model_entry.get())
            self.model_entry.delete(0, tk.END)
            self.refresh_techs()
            self.refresh_booking_data()
            messagebox.showinfo("Готово", "Техника добавлена")
        except ValidationError as exc:
            messagebox.showerror("Не удалось добавить технику", str(exc))

    def refresh_techs(self):
        for item in self.tech_tree.get_children():
            self.tech_tree.delete(item)
        owner_id = None if self.user["role"] == "admin" else self.user["id"]
        for t in dal.proc_techs_select(owner_id):
            self.tech_tree.insert("", "end", values=(t["id"], t["username"], t["type_name"], t["model"]))

    def build_report_tab(self):
        buttons = ttk.Frame(self.tab_report)
        buttons.pack(fill="x", pady=(0, 8))
        ttk.Button(buttons, text="Отчёт по услугам", command=self.load_service_report).pack(side="left", padx=4)
        ttk.Button(buttons, text="Отчёт по месяцам", command=self.load_monthly_report).pack(side="left", padx=4)
        self.report_tree = ttk.Treeview(self.tab_report, show="headings", height=20)
        self.report_tree.pack(fill="both", expand=True)
        self.load_service_report()

    def _fill_report(self, columns, rows):
        self.report_tree.delete(*self.report_tree.get_children())
        self.report_tree["columns"] = tuple(c[0] for c in columns)
        for col, title, width in columns:
            self.report_tree.heading(col, text=title)
            self.report_tree.column(col, width=width, anchor="w")
        for row in rows:
            self.report_tree.insert("", "end", values=row)

    def load_service_report(self):
        self._load_report(False)
    def load_monthly_report(self):
        self._load_report(True)

    def _load_report(self, monthly):
        try:
            data = self.admin.monthly_report(self.user) if monthly else self.admin.service_report(self.user)
            if monthly:
                cols = (("month", "Месяц", 180), ("count", "Записей", 100), ("revenue", "Выручка", 140), ("average", "Средняя цена услуги", 180))
                rows = [(r["month"], r["appointments"], f"{r['revenue']:.2f}", r["avg_service_price"] or 0) for r in data]
            else:
                cols = (("name", "Услуга", 250), ("count", "Записей", 100), ("revenue", "Выручка", 140), ("duration", "Средняя длительность, ч", 180))
                rows = [(r["service_name"], r["appointments"], f"{r['revenue']:.2f}", r["avg_duration_hours"]) for r in data]
            self._fill_report(cols, rows)
        except AccessDeniedError as exc:
            messagebox.showerror("Доступ запрещён", str(exc))

    def build_audit_tab(self):
        columns = (("id", "ID", 55), ("table", "Таблица", 120), ("operation", "Операция", 90),
                   ("data", "Данные", 440), ("user", "Пользователь", 120), ("date", "Дата изменения", 150))
        self.audit_tree = ttk.Treeview(self.tab_audit, columns=tuple(c[0] for c in columns), show="headings", height=20)
        for col, title, width in columns:
            self.audit_tree.heading(col, text=title)
            self.audit_tree.column(col, width=width, anchor="w")
        self.audit_tree.pack(fill="both", expand=True)
        for r in self.admin.audit(self.user):
            self.audit_tree.insert("", "end", values=(r["id"], r["table_name"], r["operation"],
                r["data"], r["username"], r["changed_at"]))


def main():
    dal.init_db()
    root = tk.Tk()
    TechRepairApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
