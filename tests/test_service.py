"""Real SQLite business tests; no mocks or third-party test dependencies."""
import csv
import io
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from hrm.service import HRMError, HRMService


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.db"
        self.service = HRMService(self.path, seed=False)
        self.admin = self.service.login("admin", "Admin123!")
        self.hr = self.service.login("hr", "Hr123456!")
        self.payroll_user = self.service.login("payroll", "Pay123456!")
        self.viewer = self.service.login("viewer", "View123456!")
        self.department = self.service.list_records("departments", {}, self.admin)["items"][0]

    def tearDown(self):
        self.temp.cleanup()

    def employee(self, number="T001", **extra):
        data = {"employee_no": number, "name": "测试员工", "department_id": self.department["id"], "hire_date": "2026-01-01", "base_salary": "10000"}
        data.update(extra)
        return self.service.create("employees", data, self.admin)

    def create(self, resource, **data):
        return self.service.create(resource, data, self.admin)

    def assert_error(self, action, status=400):
        with self.assertRaises(HRMError) as caught:
            action()
        self.assertEqual(caught.exception.status, status)
        self.assertTrue(caught.exception.message)

    def test_login_uses_password_hash_and_omits_password(self):
        self.assertEqual(self.admin["permissions"], ["all"])
        self.assert_error(lambda: self.service.login("admin", "wrong"), 401)
        rows = self.service.list_records("users", {}, self.admin)["items"]
        self.assertTrue(all("password" not in row and "password_hash" not in row for row in rows))
        with closing(sqlite3.connect(self.path)) as conn:
            raw = conn.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
        self.assertNotIn("Admin123!", raw)
        self.assertTrue(raw.startswith("pbkdf2_sha256$"))

    def test_permissions_are_refreshed_and_query_user_cannot_write(self):
        employee = self.employee()
        self.assertEqual(self.service.list_records("employees", {}, self.viewer)["total"], 1)
        self.assert_error(lambda: self.service.update("employees", employee["id"], {"name": "越权"}, self.viewer), 403)
        self.assert_error(lambda: self.service.list_records("users", {}, self.viewer), 403)
        self.assert_error(lambda: self.service.list_records("payroll", {}, self.hr), 403)
        self.assert_error(lambda: self.service.create("employees", {"name": "越权"}, {**self.viewer, "permissions": ["all"]}), 403)
        self.service.update("users", self.hr["id"], {"role_id": self.viewer["role_id"]} if "role_id" in self.viewer else {"role_id": next(x["id"] for x in self.service.list_records("roles", {}, self.admin)["items"] if x["code"] == "viewer")}, self.admin)
        self.assertEqual(self.service.user(self.hr["id"])["permissions"], ["query", "reports"])
        self.assert_error(lambda: self.service.create("employees", {"name": "越权"}, self.hr), 403)
        employee_meta = self.service.meta(self.viewer)["resources"]["employees"]
        self.assertEqual(employee_meta["can_write"], False)
        self.assertTrue(employee_meta["readonly"])

    def test_crud_persists_search_filters_and_audit(self):
        employee = self.employee(name="林小川")
        self.assertEqual(employee["department_name"], self.department["name"])
        updated = self.service.update("employees", employee["id"], {"phone": "13800000000"}, self.hr)
        self.assertEqual(updated["phone"], "13800000000")
        self.assertEqual(self.service.list_records("employees", {"q": "林", "department": self.department["id"], "status": "在职"}, self.viewer)["total"], 1)
        self.assertEqual(HRMService(self.path, seed=False).list_records("employees", {}, self.admin)["total"], 1)
        self.assertGreaterEqual(len(self.service.audit(self.admin)["items"]), 2)
        self.service.delete("employees", employee["id"], self.admin)
        self.assertEqual(self.service.list_records("employees", {}, self.admin)["total"], 0)

    def test_employee_validation_rejects_duplicate_invalid_and_unknown_fields(self):
        self.employee()
        self.assert_error(lambda: self.employee())
        self.assert_error(lambda: self.employee("T002", hire_date="2026-02-30"))
        self.assert_error(lambda: self.employee("T002", department_id=9999))
        self.assert_error(lambda: self.employee("T002", base_salary="NaN"))
        self.assert_error(lambda: self.employee("T002", base_salary=-1))
        self.assert_error(lambda: self.employee("T002", permission="all"))
        self.assert_error(lambda: self.employee("T002", status="离职"))
        self.assert_error(lambda: self.employee("T002", hire_date="2026-05-01", resign_date="2026-04-01", status="离职"))

    def test_transfers_update_employee_and_referenced_deletion_is_rejected(self):
        employee = self.employee()
        target = self.create("departments", name="新部门", code="NEW")
        self.create("transfers", employee_id=employee["id"], to_department_id=target["id"], transfer_date="2026-10-01", position="主管", reason="内部调动")
        updated = self.service.list_records("employees", {}, self.admin)["items"][0]
        self.assertEqual(updated["department_id"], target["id"])
        self.assertEqual(updated["position"], "主管")
        self.assert_error(lambda: self.service.delete("departments", target["id"], self.admin))
        self.assert_error(lambda: self.service.delete("employees", employee["id"], self.admin))

    def test_payroll_decimal_math_and_paid_records_are_locked(self):
        employee = self.employee()
        rates = self.service.list_records("insurance_rates", {}, self.admin)["items"][0]
        self.service.update("insurance_rates", rates["id"], {"employee_rate": "0.1", "employer_rate": "0.2"}, self.admin)
        self.create("social_insurance", employee_id=employee["id"], base="10000", start_date="2026-01-01", status="参保")
        rate = self.create("overtime_rates", name="测试标准", hourly_rate="50")
        self.create("overtime", employee_id=employee["id"], month="2026-10", hours="2", rate_id=rate["id"])
        self.create("utilities", employee_id=employee["id"], month="2026-10", water_fee="30", electricity_fee="50")
        self.create("piecework", employee_id=employee["id"], month="2026-10", quantity="10", unit_price="20", description="成品")
        self.create("hourly_work", employee_id=employee["id"], month="2026-10", hours="3", hourly_rate="100", description="值班")
        result = self.service.generate_payroll("2026-10", self.payroll_user)
        self.assertEqual(result["count"], 1)
        row = result["items"][0]
        self.assertEqual(Decimal(str(row["net_salary"])), Decimal("9520.00"))
        self.assertEqual(Decimal(str(row["employer_insurance"])), Decimal("2000.00"))
        self.assertEqual(self.service.pay_payroll("2026-10", [row["id"]], self.payroll_user), {"count": 1})
        self.assert_error(lambda: self.service.pay_payroll("2026-10", [row["id"]], self.payroll_user))
        self.assert_error(lambda: self.service.update("payroll", row["id"], {"notes": "修改"}, self.admin))
        self.assert_error(lambda: self.service.delete("payroll", row["id"], self.admin))
        self.service.update("employees", employee["id"], {"base_salary": "20000"}, self.admin)
        regenerated = self.service.generate_payroll("2026-10", self.admin)["items"][0]
        self.assertEqual(Decimal(str(regenerated["net_salary"])), Decimal("9520.00"))
        self.assertEqual(regenerated["status"], "已发放")

    def test_unpaid_approved_leave_rewards_and_employment_period(self):
        employee = self.employee(base_salary="2175")
        self.create("leaves", employee_id=employee["id"], leave_type="事假", start_date="2026-09-30", end_date="2026-10-02", days="3", paid="否", status="已批准", reason="家事")
        self.create("leaves", employee_id=employee["id"], leave_type="事假", start_date="2026-10-05", end_date="2026-10-05", days="1", paid="否", status="待审批", reason="待批准")
        self.create("rewards", employee_id=employee["id"], date="2026-10-01", kind="奖励", amount="100.15", reason="贡献")
        self.create("rewards", employee_id=employee["id"], date="2026-10-02", kind="处罚", amount="0.05", reason="迟到")
        self.employee("FUTURE", hire_date="2026-11-01")
        self.employee("PAST", status="离职", resign_date="2026-09-30")
        result = self.service.generate_payroll("2026-10", self.admin)
        self.assertEqual(result["count"], 1)
        self.assertEqual(Decimal(str(result["items"][0]["leave_deduction"])), Decimal("200.00"))
        self.assertEqual(Decimal(str(result["items"][0]["net_salary"])), Decimal("2075.10"))

    def test_payroll_rejects_bad_month_and_atomic_payment(self):
        self.employee()
        for month in ["2026-13", "2026-1", "bad"]:
            self.assert_error(lambda m=month: self.service.generate_payroll(m, self.admin))
        row = self.service.generate_payroll("2026-10", self.admin)["items"][0]
        self.assert_error(lambda: self.service.pay_payroll("2026-10", [row["id"], 99999], self.admin), 404)
        self.assertEqual(self.service.list_records("payroll", {"month": "2026-10"}, self.admin)["items"][0]["status"], "待发放")

    def test_empty_optional_numeric_fields_default_to_zero(self):
        employee = self.employee(base_salary="")
        self.create("utilities", employee_id=employee["id"], month="2026-10", water_fee="", electricity_fee="")
        row = self.service.generate_payroll("2026-10", self.admin)["items"][0]
        self.assertEqual(Decimal(row["net_salary"]), Decimal("0"))

    def test_historical_insurance_uses_coverage_dates(self):
        employee = self.employee()
        self.create("social_insurance", employee_id=employee["id"], base="10000", start_date="2026-01-01", end_date="2026-09-30", status="停保")
        september = self.service.generate_payroll("2026-09", self.admin)["items"][0]
        october = self.service.generate_payroll("2026-10", self.admin)["items"][0]
        self.assertEqual(Decimal(september["employee_insurance"]), Decimal("1050.00"))
        self.assertEqual(Decimal(october["employee_insurance"]), Decimal("0.00"))

    def test_birthday_report_dashboard_and_excel_safe_csv(self):
        tomorrow = date.today() + timedelta(days=1)
        self.employee(name="=测试", birthday=tomorrow.replace(year=2000).isoformat(), gender="女", education="本科")
        birthdays = self.service.birthdays(30, self.viewer)
        self.assertEqual(birthdays["total"], 1)
        self.assertEqual(birthdays["items"][0]["days_until"], 1)
        report = self.service.reports(2026, self.viewer)
        self.assertEqual(report["summary"]["active"], 1)
        self.assertEqual(len(report["monthly"]), 12)
        self.assertEqual(report["monthly"][0]["joined"], 1)
        self.assertEqual(self.service.dashboard(self.viewer)["metrics"]["employees"], 1)
        output = self.service.export_csv("employees", {}, self.viewer)
        self.assertIsInstance(output, str)
        self.assertIn("'=测试", output)
        self.assert_error(lambda: self.service.birthdays(-1, self.viewer))
        self.assert_error(lambda: self.service.reports("invalid", self.viewer))

    def test_seed_metadata_all_resources_and_no_business_data_without_seed(self):
        resources = self.service.meta(self.admin)["resources"]
        expected = {"employees", "social_insurance", "rewards", "transfers", "certificates", "interns", "leaves", "courses", "internal_training", "frontline_training", "salary_grades", "overtime_rates", "utilities", "overtime", "piecework", "hourly_work", "payroll", "notices", "insurance_rates", "menus", "roles", "users", "departments", "dictionaries"}
        self.assertEqual(set(resources), expected)
        self.assertEqual(self.service.list_records("employees", {}, self.admin)["total"], 0)
        seeded = HRMService(Path(self.temp.name) / "demo.db")
        admin = seeded.login("admin", "Admin123!")
        self.assertGreaterEqual(seeded.list_records("employees", {}, admin)["total"], 12)
        for key in resources:
            with self.subTest(resource=key):
                self.assertGreater(seeded.list_records(key, {}, admin)["total"], 0)

    def test_roles_password_changes_and_last_admin_safety(self):
        self.assert_error(lambda: self.service.update("users", self.admin["id"], {"status": "停用"}, self.admin))
        self.assert_error(lambda: self.service.delete("users", self.admin["id"], self.admin))
        self.assert_error(lambda: self.create("roles", code="bad", name="无效", permissions=["invalid"]))
        self.service.update("users", self.viewer["id"], {"password": "Changed123!"}, self.admin)
        self.assert_error(lambda: self.service.login("viewer", "View123456!"), 401)
        self.assertEqual(self.service.login("viewer", "Changed123!")["id"], self.viewer["id"])

    def test_navigation_configuration_changes_metadata(self):
        menu = next(r for r in self.service.list_records("menus", {}, self.admin)["items"] if r["module"] == "personnel")
        self.service.update("menus", menu["id"], {"name": "员工事务", "visible": "否"}, self.admin)
        self.assertNotIn("personnel", [m["id"] for m in self.service.meta(self.admin)["modules"]])
        self.service.update("menus", menu["id"], {"visible": "是", "sort_order": "0"}, self.admin)
        self.assertEqual("员工事务", self.service.meta(self.admin)["modules"][0]["title"])

    def test_dictionary_options_are_used_and_validated(self):
        self.create("dictionaries", category="学历", code="associate_special", label="职业本科", sort_order="10", status="启用")
        education = next(f for f in self.service.meta(self.admin)["resources"]["employees"]["fields"] if f["name"] == "education")
        self.assertIn("职业本科", education["options"])
        employee = self.employee(education="职业本科")
        self.assertEqual("职业本科", employee["education"])

    def test_empty_select_cannot_silently_drop_payroll_inputs(self):
        employee = self.employee()
        self.assert_error(lambda: self.create("rewards", employee_id=employee["id"], date="2026-10-01", kind="", amount="500", reason="贡献"))
        self.assert_error(lambda: self.service.update("employees", employee["id"], {"status": ""}, self.admin))

    def test_old_transfers_cannot_overwrite_later_organization(self):
        employee = self.employee(position="工程师")
        second = self.create("departments", code="D2", name="第二部门")
        third = self.create("departments", code="D3", name="第三部门")
        fourth = self.create("departments", code="D4", name="第四部门")
        first_transfer = self.create("transfers", employee_id=employee["id"], to_department_id=second["id"], transfer_date="2026-02-01", position="主管")
        self.create("transfers", employee_id=employee["id"], to_department_id=third["id"], transfer_date="2026-03-01", position="经理")
        self.assert_error(lambda: self.service.update("transfers", first_transfer["id"], {"to_department_id": fourth["id"]}, self.admin))
        self.assertEqual(third["id"], self.service.list_records("employees", {}, self.admin)["items"][0]["department_id"])

    def test_draft_notices_are_not_public(self):
        self.create("notices", title="未公布", content="草稿机密", date="2026-10-01", status="草稿")
        self.assertEqual(0, self.service.list_records("notices", {}, self.viewer)["total"])
        self.assertNotIn("未公布", self.service.export_csv("notices", {}, self.viewer))
        self.assertEqual(1, self.service.list_records("notices", {}, self.hr)["total"])

    def test_settings_only_account_has_no_employee_dashboard_details(self):
        self.employee()
        role = self.create("roles", code="configonly", name="配置管理员", permissions=["settings"], read_only="否")
        account = self.create("users", username="configonly", name="配置管理员", role_id=role["id"], password="Config123!")
        user = self.service.login("configonly", "Config123!")
        self.assert_error(lambda: self.service.list_records("employees", {}, user), 403)
        data = self.service.dashboard(user)
        self.assertEqual([], data["recent_employees"])
        self.assertEqual([], data["upcoming_birthdays"])

    def test_restart_does_not_require_original_admin_or_reseed(self):
        role = next(r for r in self.service.list_records("roles", {}, self.admin)["items"] if r["code"] == "admin")
        self.create("users", username="replacement", name="新管理员", role_id=role["id"], password="Replace123!")
        self.service.delete("users", self.admin["id"], self.admin)
        restarted = HRMService(self.path)
        user = restarted.login("replacement", "Replace123!")
        self.assertEqual(0, restarted.list_records("employees", {}, user)["total"])

    def test_latest_transfer_position_and_rollback_remain_consistent(self):
        employee = self.employee(position="工程师")
        target = self.create("departments", code="MOVE", name="调入部门")
        move = self.create("transfers", employee_id=employee["id"], to_department_id=target["id"], transfer_date="2026-02-01", position="主管")
        self.service.update("transfers", move["id"], {"position": "高级主管"}, self.admin)
        self.assertEqual("高级主管", self.service.list_records("employees", {}, self.admin)["items"][0]["position"])
        self.service.delete("transfers", move["id"], self.admin)
        restored = self.service.list_records("employees", {}, self.admin)["items"][0]
        self.assertEqual(self.department["id"], restored["department_id"])
        self.assertEqual("工程师", restored["position"])


if __name__ == "__main__":
    unittest.main()
