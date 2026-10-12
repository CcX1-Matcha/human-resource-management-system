"""SQLite business rules for the HRM application (Python standard library only)."""
import calendar
import csv
import hashlib
import hmac
import io
import json
import re
import secrets
import sqlite3
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from .schema import MODULES, RESOURCES, create_tables


class HRMError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status = status
        super().__init__(message)


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 210000).hex()
    return f"pbkdf2_sha256$210000${salt}${digest}"


def password_matches(password, stored):
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, AttributeError):
        return False


class HRMService:
    def __init__(self, db_path, seed=True):
        self.db_path = str(db_path)
        if self.db_path == ":memory:":
            raise ValueError("请使用数据库文件路径，以保证多连接持久化")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        created_demo = False
        with self._connection(write=True) as conn:
            create_tables(conn)
            from .seed import seed_base, seed_demo
            fresh = not conn.execute("SELECT 1 FROM app_state WHERE key='base_initialized'").fetchone()
            seed_base(conn, password_hash)
            if seed and fresh:
                seed_demo(conn)
                created_demo = True
                conn.execute("INSERT INTO app_state(key,value) VALUES('demo_seeded','1')")
        if created_demo:
            with self._connection() as conn:
                initial_admin = conn.execute("SELECT u.id FROM users u JOIN roles r ON r.id=u.role_id WHERE u.status='启用' AND r.code='admin' LIMIT 1").fetchone()[0]
            self.generate_payroll(date.today().strftime("%Y-%m"), self.user(initial_admin))

    @contextmanager
    def _connection(self, write=False):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            if "FOREIGN KEY" in str(exc):
                raise HRMError("该记录被其他业务引用，不能删除；请先处理关联记录") from exc
            raise HRMError("记录已存在，请检查工号、账号、编码或重复关联记录") from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _resource(self, key):
        if key not in RESOURCES:
            raise HRMError("未找到该业务模块", 404)
        return RESOURCES[key]

    def _user(self, conn, user_id):
        if isinstance(user_id, bool):
            return None
        row = conn.execute("SELECT u.id,u.username,u.name,u.status,r.code AS role,r.permissions,r.read_only FROM users u JOIN roles r ON r.id=u.role_id WHERE u.id=?", (user_id,)).fetchone()
        if not row or row["status"] != "启用":
            return None
        return {"id": row["id"], "username": row["username"], "name": row["name"], "role": row["role"], "permissions": json.loads(row["permissions"] or "[]"), "_read_only": row["read_only"] == "是"}

    def _auth(self, conn, supplied):
        current = self._user(conn, supplied.get("id") if isinstance(supplied, dict) else None)
        if not current:
            raise HRMError("登录已失效，请重新登录", 401)
        return current

    def _allowed(self, user, key, write=False):
        permissions = user["permissions"]
        if write and user["_read_only"]:
            return False
        if "all" in permissions:
            return True
        module = RESOURCES[key]["module"]
        if write:
            # Public query permission grants viewing; notices are published by personnel staff.
            return module in permissions and module not in ("query", "reports") or key == "notices" and "personnel" in permissions
        if module in permissions:
            return True
        if key == "employees" and any(p in permissions for p in ("query", "training", "payroll", "reports")):
            return True
        if key in ("departments", "dictionaries", "salary_grades", "overtime_rates"):
            return bool(permissions)
        if key == "courses" and "personnel" in permissions:
            return True
        return False

    def _check(self, conn, supplied, resource, write=False):
        self._resource(resource)
        user = self._auth(conn, supplied)
        if not self._allowed(user, resource, write):
            raise HRMError("当前账号没有该操作权限", 403)
        return user

    def _module_check(self, conn, supplied, module):
        user = self._auth(conn, supplied)
        if "all" not in user["permissions"] and module not in user["permissions"]:
            raise HRMError("当前账号没有该操作权限", 403)
        return user

    def login(self, username, password):
        if not isinstance(username, str) or not isinstance(password, str):
            raise HRMError("请输入正确的账号和密码", 401)
        with self._connection() as conn:
            row = conn.execute("SELECT id,password_hash,status FROM users WHERE username=?", (username.strip(),)).fetchone()
            if not row or row["status"] != "启用" or not password_matches(password, row["password_hash"]):
                raise HRMError("账号或密码错误，或账号已停用", 401)
            user = self._user(conn, row["id"])
            user.pop("_read_only")
            return user

    def user(self, user_id):
        with self._connection() as conn:
            result = self._user(conn, user_id)
            if result:
                result.pop("_read_only")
            return result

    def meta(self, user):
        with self._connection() as conn:
            current = self._auth(conn, user)
            resources = deepcopy(RESOURCES)
            for key, definition in resources.items():
                definition["fields"] = self._fields(conn, key)
                definition["can_read"] = self._allowed(current, key)
                definition["can_write"] = self._allowed(current, key, True)
                definition["readonly"] = not definition["can_write"]
                # Use reference fields as columns: the UI renders their linked names
                # with the original Chinese labels instead of exposing foreign IDs.
                linked = {f["name"][:-3] + "_name": f["name"] for f in definition["fields"] if f.get("reference")}
                definition["columns"] = [linked.get(column, column) for column in definition["columns"]]
            menus = {r["module"]: r for r in conn.execute("SELECT * FROM menus ORDER BY id DESC")}
            modules = []
            for index, module in enumerate(MODULES):
                menu = menus.get(module["id"])
                if menu and menu["visible"] == "否" and module["id"] != "settings":
                    continue
                modules.append({**module, "title": menu["name"] if menu else module["title"], "sort_order": float(menu["sort_order"]) if menu else index + 1})
            modules.sort(key=lambda m: m["sort_order"])
            return {"modules": modules, "resources": resources, "permissions": [{"id": "all", "title": "全部权限"}] + [{"id": m["id"], "title": m["title"]} for m in MODULES]}

    def _fields(self, conn, resource):
        fields = deepcopy(RESOURCES[resource]["fields"])
        categories = {("employees", "education"): "学历", ("leaves", "leave_type"): "假别"}
        for field in fields:
            category = categories.get((resource, field["name"]))
            if category:
                labels = [r[0] for r in conn.execute("SELECT label FROM dictionaries WHERE category=? AND status='启用' ORDER BY CAST(sort_order AS REAL),id", (category,))]
                field["options"] = list(dict.fromkeys([*field["options"], *labels]))
        return fields

    def _decode(self, conn, resource, row):
        result = dict(row)
        result.pop("password_hash", None)
        result.pop("password", None)
        for f in RESOURCES[resource]["fields"]:
            if f["type"] == "permissions":
                result[f["name"]] = json.loads(result.get(f["name"]) or "[]")
            elif f.get("reference"):
                reference = f["reference"]
                target_id = result.get(f["name"])
                label = None
                if target_id:
                    target = conn.execute(f'SELECT * FROM "{reference}" WHERE id=?', (target_id,)).fetchone()
                    if target:
                        label = target["name"] if "name" in target.keys() else target["label"] if "label" in target.keys() else str(target_id)
                result[f["name"][:-3] + "_name"] = label or ""
        return result

    def _rows(self, conn, resource, filters=None):
        filters = filters or {}
        rows = [self._decode(conn, resource, row) for row in conn.execute(f'SELECT * FROM "{resource}" ORDER BY id DESC')]
        q = str(filters.get("q", "") or "").strip().casefold()
        if q:
            rows = [row for row in rows if any(q in str(value).casefold() for value in row.values())]
        department = filters.get("department", filters.get("department_id"))
        if department not in (None, "", "all"):
            try:
                department = int(department)
            except (ValueError, TypeError):
                raise HRMError("部门筛选无效")
            def matches(row):
                if "department_id" in row:
                    return row["department_id"] == department
                if row.get("employee_id"):
                    employee = conn.execute("SELECT department_id FROM employees WHERE id=?", (row["employee_id"],)).fetchone()
                    return employee and employee[0] == department
                return False
            rows = [row for row in rows if matches(row)]
        if filters.get("status") not in (None, "", "all"):
            rows = [r for r in rows if r.get("status") == filters["status"]]
        if filters.get("month"):
            self._month(filters["month"])
            rows = [r for r in rows if r.get("month") == filters["month"]]
        return rows

    def list_records(self, resource, filters, user):
        with self._connection() as conn:
            current = self._check(conn, user, resource)
            items = self._rows(conn, resource, filters)
            if resource == "notices" and not self._allowed(current, resource, True):
                items = [r for r in items if r["status"] == "已发布"]
            return {"items": items, "total": len(items)}

    def _date(self, value, label):
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise HRMError(f"{label}应为 YYYY-MM-DD 格式")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise HRMError(f"{label}不是有效日期") from exc

    def _month(self, value):
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
            raise HRMError("月份应为 YYYY-MM 格式")
        try:
            first = date.fromisoformat(value + "-01")
            last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
            return first, last
        except ValueError as exc:
            raise HRMError("月份不是有效月份") from exc

    def _validate(self, conn, resource, data, original=None):
        if not isinstance(data, dict):
            raise HRMError("记录数据应为 JSON 对象")
        definitions = {f["name"]: f for f in self._fields(conn, resource)}
        for key in data:
            if key not in definitions:
                raise HRMError(f"不能提交未知字段：{key}")
            if definitions[key].get("readonly"):
                raise HRMError(f"{definitions[key]['label']}由系统生成，不能修改")
        clean = {}
        for name, f in definitions.items():
            if f.get("readonly"):
                continue
            if original is not None and name not in data:
                continue
            value = data.get(name, f.get("default"))
            if f["type"] == "password" and not value:
                if original is None:
                    raise HRMError("新用户必须设置密码")
                continue
            if value in (None, ""):
                if f["type"] == "select" and not f.get("reference"):
                    raise HRMError(f"请选择{f['label']}")
                if f["required"]:
                    raise HRMError(f"请填写{f['label']}")
                clean[name] = None if f.get("reference") else str(f.get("default", "0")) if f["type"] == "number" else ""
                continue
            if f.get("reference"):
                if isinstance(value, bool) or not re.fullmatch(r"[1-9]\d*", str(value)):
                    raise HRMError(f"请选择有效的{f['label']}")
                value = int(value)
                if not conn.execute(f'SELECT 1 FROM "{f["reference"]}" WHERE id=?', (value,)).fetchone():
                    raise HRMError(f"{f['label']}不存在或已删除")
            elif f["type"] == "number":
                if isinstance(value, bool):
                    raise HRMError(f"{f['label']}必须是有效数字")
                try:
                    numeric = Decimal(str(value))
                except (InvalidOperation, ValueError, TypeError) as exc:
                    raise HRMError(f"{f['label']}必须是有效数字") from exc
                if not numeric.is_finite() or abs(numeric) > Decimal("1000000000"):
                    raise HRMError(f"{f['label']}超出有效范围")
                if f.get("minimum") is not None and numeric < Decimal(f["minimum"]):
                    raise HRMError(f"{f['label']}不得小于{f['minimum']}")
                if f.get("maximum") is not None and numeric > Decimal(f["maximum"]):
                    raise HRMError(f"{f['label']}不得大于{f['maximum']}")
                if abs(numeric.as_tuple().exponent) > 6:
                    raise HRMError(f"{f['label']}最多保留六位小数")
                value = format(numeric, "f")
            elif f["type"] == "permissions":
                valid = {"all", *[m["id"] for m in MODULES]}
                if not isinstance(value, list) or not value or any(not isinstance(p, str) or p not in valid for p in value):
                    raise HRMError("请选择有效的模块权限")
                value = json.dumps(list(dict.fromkeys(value)), ensure_ascii=False)
            else:
                if not isinstance(value, str):
                    raise HRMError(f"{f['label']}应为文本")
                if f["type"] != "password":
                    value = value.strip()
                if len(value) > (10000 if f["type"] == "textarea" else 255):
                    raise HRMError(f"{f['label']}内容过长")
                if f["required"] and not value:
                    raise HRMError(f"请填写{f['label']}")
                if f["type"] == "date":
                    self._date(value, f["label"])
                elif f["type"] == "month":
                    self._month(value)
                elif f["type"] == "select" and value not in f["options"] and (not original or value != original[name]):
                    raise HRMError(f"{f['label']}的选项无效")
                elif f["type"] == "password":
                    if len(value) < 8:
                        raise HRMError("密码至少需要8个字符")
                    clean["password_hash"] = password_hash(value)
                    continue
                elif f["type"] == "email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
                    raise HRMError("邮箱格式无效")
            clean[name] = value
        merged = {**(dict(original) if original else {}), **clean}
        for start, end in [("start_date", "end_date"), ("issued_date", "expiry_date"), ("hire_date", "resign_date")]:
            if merged.get(start) and merged.get(end) and merged[start] > merged[end]:
                raise HRMError("结束日期不得早于开始日期")
        if resource == "employees":
            if merged.get("birthday") and self._date(merged["birthday"], "出生日期") > date.today():
                raise HRMError("出生日期不能晚于今天")
            if merged.get("status") == "离职" and not merged.get("resign_date"):
                raise HRMError("离职员工必须填写离职日期")
            if merged.get("status") != "离职" and merged.get("resign_date"):
                raise HRMError("填写离职日期时，员工状态须设为离职")
            if merged.get("birthday") and merged.get("hire_date") and merged["birthday"] > merged["hire_date"]:
                raise HRMError("入职日期不得早于出生日期")
        if resource == "leaves":
            span = (self._date(merged["end_date"], "结束日期") - self._date(merged["start_date"], "开始日期")).days + 1
            if Decimal(merged["days"]) > span:
                raise HRMError("请假天数不得超过起止日期范围")
        if resource == "social_insurance" and merged.get("status") == "停保" and not merged.get("end_date"):
            raise HRMError("停保记录必须填写结束日期")
        if resource == "departments" and original and merged.get("parent_id"):
            visited = {original["id"]}
            parent = merged["parent_id"]
            while parent:
                if parent in visited:
                    raise HRMError("上级部门不能形成循环")
                visited.add(parent)
                parent_row = conn.execute("SELECT parent_id FROM departments WHERE id=?", (parent,)).fetchone()
                parent = parent_row[0] if parent_row else None
        if resource in ("users", "roles") and original:
            self._protect_admin(conn, resource, original["id"], merged)
        if resource == "insurance_rates" and original is None and conn.execute("SELECT 1 FROM insurance_rates").fetchone():
            raise HRMError("系统使用统一社保比例，请编辑现有方案")
        if resource == "menus":
            duplicate = conn.execute("SELECT id FROM menus WHERE module=? AND id!=?", (merged["module"], original["id"] if original else 0)).fetchone()
            if duplicate:
                raise HRMError("该模块已有导航菜单，请编辑现有菜单")
            if merged["module"] == "settings" and merged["visible"] == "否":
                raise HRMError("系统设置菜单需保留，以便继续维护导航配置")
        return clean

    def _protect_admin(self, conn, resource, record_id, merged=None):
        admins = conn.execute("SELECT u.id,u.role_id FROM users u JOIN roles r ON r.id=u.role_id WHERE u.status='启用' AND r.read_only='否' AND (r.permissions LIKE '%\"all\"%' OR r.permissions LIKE '%\"settings\"%')").fetchall()
        affected = [r for r in admins if r["id"] == record_id] if resource == "users" else [r for r in admins if r["role_id"] == record_id]
        if not affected:
            return
        remains_admin = False
        if merged:
            if resource == "roles":
                permissions = json.loads(merged["permissions"])
                remains_admin = merged.get("read_only") != "是" and any(p in permissions for p in ("all", "settings"))
            else:
                role = conn.execute("SELECT permissions,read_only FROM roles WHERE id=?", (merged["role_id"],)).fetchone()
                remains_admin = merged["status"] == "启用" and role["read_only"] != "是" and any(p in json.loads(role["permissions"]) for p in ("all", "settings"))
        if not remains_admin and len(affected) == len(admins):
            raise HRMError("必须保留至少一个启用的系统管理员")

    def _record(self, conn, resource, record_id):
        if isinstance(record_id, bool) or not re.fullmatch(r"[1-9]\d*", str(record_id)):
            raise HRMError("记录编号无效", 404)
        row = conn.execute(f'SELECT * FROM "{resource}" WHERE id=?', (record_id,)).fetchone()
        if not row:
            raise HRMError("记录不存在或已删除", 404)
        return row

    def _audit(self, conn, user, action, resource, record_id, detail=""):
        conn.execute("INSERT INTO audit_log(user_id,username,action,resource,record_id,detail,created_at) VALUES(?,?,?,?,?,?,?)", (user["id"], user["username"], action, resource, record_id, detail, datetime.now().isoformat(timespec="seconds")))

    def _insert(self, conn, resource, data):
        columns = list(data)
        sql = f'INSERT INTO "{resource}" (' + ",".join(f'"{key}"' for key in columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")"
        return conn.execute(sql, [data[k] for k in columns]).lastrowid

    def _transfer(self, conn, data):
        employee = self._record(conn, "employees", data["employee_id"])
        if employee["status"] == "离职":
            raise HRMError("离职员工不能调动")
        if data["transfer_date"] < employee["hire_date"]:
            raise HRMError("调动日期不能早于入职日期")
        if not data.get("from_department_id"):
            data["from_department_id"] = employee["department_id"]
        if data["from_department_id"] == data["to_department_id"]:
            raise HRMError("调入部门不能与原部门相同")
        conn.execute("UPDATE employees SET department_id=?,position=? WHERE id=?", (data["to_department_id"], data.get("position") or employee["position"], employee["id"]))

    def create(self, resource, data, user):
        with self._connection(write=True) as conn:
            current = self._check(conn, user, resource, True)
            if resource == "payroll":
                raise HRMError("工资请使用按月生成操作")
            clean = self._validate(conn, resource, data)
            if resource == "transfers":
                clean["from_position"] = self._record(conn, "employees", clean["employee_id"])["position"]
                self._transfer(conn, clean)
            record_id = self._insert(conn, resource, clean)
            self._audit(conn, current, "新增", resource, record_id)
            return self._decode(conn, resource, self._record(conn, resource, record_id))

    def update(self, resource, record_id, data, user):
        with self._connection(write=True) as conn:
            current = self._check(conn, user, resource, True)
            original = self._record(conn, resource, record_id)
            if resource == "payroll" and original["status"] == "已发放":
                raise HRMError("已发放工资已锁定，不能修改")
            clean = self._validate(conn, resource, data, original)
            if resource == "transfers":
                if "employee_id" in clean and clean["employee_id"] != original["employee_id"]:
                    raise HRMError("调动记录不能更换员工，请删除后重新登记")
                changed = any(name in clean and clean[name] != original[name] for name in ("to_department_id", "from_department_id", "position", "transfer_date"))
                if changed:
                    later = conn.execute("SELECT 1 FROM transfers WHERE employee_id=? AND id>?", (original["employee_id"], record_id)).fetchone()
                    employee = self._record(conn, "employees", original["employee_id"])
                    if later or employee["department_id"] != original["to_department_id"]:
                        raise HRMError("已有后续组织变动，不能修改历史调动的部门、岗位或日期")
                    if clean.get("from_department_id", original["from_department_id"]) != original["from_department_id"]:
                        raise HRMError("原部门是调动时的档案，不可修改")
                    merged = {**dict(original), **clean}
                    if merged["to_department_id"] != original["to_department_id"]:
                        self._transfer(conn, merged)
                    else:
                        if merged["transfer_date"] < employee["hire_date"]:
                            raise HRMError("调动日期不能早于入职日期")
                        conn.execute("UPDATE employees SET position=? WHERE id=?", (merged["position"] or employee["position"], employee["id"]))
            if clean:
                sql = f'UPDATE "{resource}" SET ' + ",".join(f'"{key}"=?' for key in clean) + " WHERE id=?"
                conn.execute(sql, [*clean.values(), record_id])
            self._audit(conn, current, "修改", resource, record_id, "、".join(k for k in clean if k != "password_hash"))
            return self._decode(conn, resource, self._record(conn, resource, record_id))

    def delete(self, resource, record_id, user):
        with self._connection(write=True) as conn:
            current = self._check(conn, user, resource, True)
            original = self._record(conn, resource, record_id)
            if resource == "payroll" and original["status"] == "已发放":
                raise HRMError("已发放工资已锁定，不能删除")
            if resource == "insurance_rates":
                raise HRMError("系统社保方案不能删除，请编辑比例")
            if resource in ("users", "roles"):
                self._protect_admin(conn, resource, int(record_id))
            if resource == "transfers":
                later = conn.execute("SELECT 1 FROM transfers WHERE employee_id=? AND id>?", (original["employee_id"], record_id)).fetchone()
                employee = self._record(conn, "employees", original["employee_id"])
                if later or employee["department_id"] != original["to_department_id"]:
                    raise HRMError("已有后续组织变动，不能删除历史调动")
                if original["from_position"] is None:
                    raise HRMError("历史记录缺少原岗位，不能自动回退；请保留记录并登记新的调动")
                conn.execute("UPDATE employees SET department_id=?,position=? WHERE id=?", (original["from_department_id"], original["from_position"], original["employee_id"]))
            conn.execute(f'DELETE FROM "{resource}" WHERE id=?', (record_id,))
            self._audit(conn, current, "删除", resource, int(record_id))
            return {"success": True}

    def _birthdays(self, conn, days):
        today = date.today()
        result = []
        for employee in self._rows(conn, "employees"):
            if employee["status"] == "离职" or not employee.get("birthday"):
                continue
            birthday = date.fromisoformat(employee["birthday"])
            def anniversary(year):
                return date(year, birthday.month, min(birthday.day, calendar.monthrange(year, birthday.month)[1]))
            upcoming = anniversary(today.year)
            if upcoming < today:
                upcoming = anniversary(today.year + 1)
            until = (upcoming - today).days
            if until <= days:
                result.append({**employee, "next_birthday": upcoming.isoformat(), "days_until": until, "age": upcoming.year - birthday.year})
        return sorted(result, key=lambda row: (row["days_until"], row["name"]))

    def birthdays(self, days, user):
        try:
            if isinstance(days, bool) or not str(days).isdigit():
                raise ValueError
            days = int(days)
            if not 0 <= days <= 366:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise HRMError("生日查询天数应为0至366的整数") from exc
        with self._connection() as conn:
            self._check(conn, user, "employees")
            items = self._birthdays(conn, days)
            return {"items": items, "total": len(items)}

    def dashboard(self, user):
        with self._connection() as conn:
            current = self._auth(conn, user)
            month = date.today().strftime("%Y-%m")
            can_employees = self._allowed(current, "employees")
            employees = self._rows(conn, "employees") if can_employees else []
            active = [r for r in employees if r["status"] != "离职"]
            departments = self._rows(conn, "departments")
            payroll = self._rows(conn, "payroll", {"month": month}) if self._allowed(current, "payroll") else []
            fields = ("id", "name", "employee_no", "department_name", "position", "hire_date", "status", "next_birthday", "days_until", "age")
            compact = lambda row: {k: row[k] for k in fields if k in row}
            return {"metrics": {"employees": len(active) if can_employees else None, "departments": len(departments), "pending_leaves": conn.execute("SELECT COUNT(*) FROM leaves WHERE status='待审批'").fetchone()[0] if self._allowed(current, "leaves") else None, "monthly_payroll": format(sum((money(r["net_salary"]) for r in payroll), Decimal(0)), ".2f") if self._allowed(current, "payroll") else None}, "department_counts": [{"label": d["name"], "value": sum(e["department_id"] == d["id"] for e in active)} for d in departments] if can_employees else [], "recent_employees": [compact(e) for e in sorted(employees, key=lambda e: e["hire_date"], reverse=True)[:5]], "upcoming_birthdays": [compact(e) for e in self._birthdays(conn, 30)[:5]] if can_employees else [], "notices": [r for r in self._rows(conn, "notices") if r["status"] == "已发布"][:5] if self._allowed(current, "notices") else [], "month": month}

    def reports(self, year, user):
        try:
            if isinstance(year, bool) or not re.fullmatch(r"\d{4}", str(year)):
                raise ValueError
            year = int(year)
            if not 1900 <= year <= 9998:
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise HRMError("统计年份应为1900至9998的整数") from exc
        with self._connection() as conn:
            self._module_check(conn, user, "reports")
            employees = self._rows(conn, "employees")
            active = [e for e in employees if e["status"] != "离职"]
            resigned = [e for e in employees if e.get("resign_date", "").startswith(str(year))]
            start = f"{year}-01-01"
            end = f"{year}-12-31"
            opening = sum(e["hire_date"] < start and (not e.get("resign_date") or e["resign_date"] >= start) for e in employees)
            closing = sum(e["hire_date"] <= end and (not e.get("resign_date") or e["resign_date"] > end) for e in employees)
            average = Decimal(opening + closing) / 2
            turnover = money(Decimal(len(resigned)) / average * 100) if average else Decimal(0)
            def groups(values):
                return [{"label": label, "value": value} for label, value in Counter(values).items()]
            today = date.today()
            ages = Counter({"25岁以下": 0, "25-34岁": 0, "35-44岁": 0, "45岁及以上": 0, "未填写": 0})
            tenures = Counter({"1年以下": 0, "1-3年": 0, "3-5年": 0, "5年及以上": 0})
            for e in active:
                if e.get("birthday"):
                    born = date.fromisoformat(e["birthday"])
                    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
                    ages["25岁以下" if age < 25 else "25-34岁" if age < 35 else "35-44岁" if age < 45 else "45岁及以上"] += 1
                else:
                    ages["未填写"] += 1
                tenure = max(0, (today - date.fromisoformat(e["hire_date"])).days / 365.2425)
                tenures["1年以下" if tenure < 1 else "1-3年" if tenure < 3 else "3-5年" if tenure < 5 else "5年及以上"] += 1
            return {"year": year, "summary": {"total": len(employees), "active": len(active), "resigned": len(resigned), "turnover_rate": float(turnover)}, "gender": groups(e["gender"] or "未填写" for e in active), "education": groups(e["education"] or "未填写" for e in active), "age": [{"label": k, "value": v} for k, v in ages.items()], "tenure": [{"label": k, "value": v} for k, v in tenures.items()], "departments": groups(e["department_name"] for e in active), "monthly": [{"month": f"{year}-{m:02d}", "joined": sum(e["hire_date"].startswith(f"{year}-{m:02d}") for e in employees), "resigned": sum((e.get("resign_date") or "").startswith(f"{year}-{m:02d}") for e in employees)} for m in range(1, 13)]}

    def _calculate_payroll(self, conn, employee, month, first, last):
        employee_id = employee["id"]
        def records(key):
            return conn.execute(f'SELECT * FROM "{key}" WHERE employee_id=? AND month=?', (employee_id, month)).fetchall()
        amounts = {"base_salary": money(employee["base_salary"])}
        amounts["overtime_pay"] = money(sum((Decimal(r["hours"]) * Decimal(conn.execute("SELECT hourly_rate FROM overtime_rates WHERE id=?", (r["rate_id"],)).fetchone()[0]) for r in records("overtime")), Decimal(0)))
        amounts["piecework_pay"] = money(sum((Decimal(r["quantity"]) * Decimal(r["unit_price"]) for r in records("piecework")), Decimal(0)))
        amounts["hourly_pay"] = money(sum((Decimal(r["hours"]) * Decimal(r["hourly_rate"]) for r in records("hourly_work")), Decimal(0)))
        rewards = conn.execute("SELECT * FROM rewards WHERE employee_id=? AND date>=? AND date<=?", (employee_id, first.isoformat(), last.isoformat())).fetchall()
        amounts["reward_amount"] = money(sum((Decimal(r["amount"]) for r in rewards if r["kind"] == "奖励"), Decimal(0)))
        amounts["penalty_amount"] = money(sum((Decimal(r["amount"]) for r in rewards if r["kind"] == "处罚"), Decimal(0)))
        amounts["utility_deduction"] = money(sum((Decimal(r["water_fee"]) + Decimal(r["electricity_fee"]) for r in records("utilities")), Decimal(0)))
        insurance = conn.execute("SELECT * FROM social_insurance WHERE employee_id=? AND start_date<=? AND (end_date='' OR end_date IS NULL OR end_date>=?)", (employee_id, last.isoformat(), first.isoformat())).fetchone()
        rate = conn.execute("SELECT employee_rate,employer_rate FROM insurance_rates ORDER BY id LIMIT 1").fetchone()
        amounts["employee_insurance"] = money(Decimal(insurance["base"]) * Decimal(rate["employee_rate"])) if insurance else Decimal("0.00")
        amounts["employer_insurance"] = money(Decimal(insurance["base"]) * Decimal(rate["employer_rate"])) if insurance else Decimal("0.00")
        leaves = conn.execute("SELECT * FROM leaves WHERE employee_id=? AND status='已批准' AND paid='否' AND start_date<=? AND end_date>=?", (employee_id, last.isoformat(), first.isoformat())).fetchall()
        leave_days = Decimal(0)
        for leave in leaves:
            start, end = date.fromisoformat(leave["start_date"]), date.fromisoformat(leave["end_date"])
            overlap = (min(end, last) - max(start, first)).days + 1
            leave_days += Decimal(leave["days"]) * Decimal(overlap) / Decimal((end - start).days + 1)
        amounts["leave_deduction"] = money(amounts["base_salary"] / Decimal("21.75") * leave_days)
        amounts["gross_salary"] = sum(amounts[k] for k in ("base_salary", "overtime_pay", "piecework_pay", "hourly_pay", "reward_amount"))
        amounts["total_deduction"] = sum(amounts[k] for k in ("penalty_amount", "utility_deduction", "employee_insurance", "leave_deduction"))
        amounts["net_salary"] = amounts["gross_salary"] - amounts["total_deduction"]
        return {"employee_id": employee_id, "month": month, **{k: format(v, ".2f") for k, v in amounts.items()}, "status": "待发放", "paid_at": "", "notes": ""}

    def generate_payroll(self, month, user):
        first, last = self._month(month)
        with self._connection(write=True) as conn:
            current = self._check(conn, user, "payroll", True)
            employees = conn.execute("SELECT * FROM employees WHERE hire_date<=? AND (resign_date='' OR resign_date IS NULL OR resign_date>=?)", (last.isoformat(), first.isoformat())).fetchall()
            eligible = {e["id"] for e in employees}
            for row in conn.execute("SELECT * FROM payroll WHERE month=? AND status!='已发放'", (month,)).fetchall():
                if row["employee_id"] not in eligible:
                    conn.execute("DELETE FROM payroll WHERE id=?", (row["id"],))
            for employee in employees:
                existing = conn.execute("SELECT * FROM payroll WHERE employee_id=? AND month=?", (employee["id"], month)).fetchone()
                if existing and existing["status"] == "已发放":
                    continue
                record = self._calculate_payroll(conn, employee, month, first, last)
                if existing:
                    record["notes"] = existing["notes"] or ""
                    conn.execute("UPDATE payroll SET " + ",".join(f'"{k}"=?' for k in record) + " WHERE id=?", [*record.values(), existing["id"]])
                else:
                    self._insert(conn, "payroll", record)
            self._audit(conn, current, "生成工资", "payroll", None, month)
            items = self._rows(conn, "payroll", {"month": month})
            return {"items": items, "count": len(items)}

    def pay_payroll(self, month, ids, user):
        self._month(month)
        if ids is not None and (not isinstance(ids, list) or any(isinstance(i, bool) or not isinstance(i, int) or i <= 0 for i in ids)):
            raise HRMError("工资编号应为正整数数组")
        with self._connection(write=True) as conn:
            current = self._check(conn, user, "payroll", True)
            if ids is not None:
                if not ids:
                    raise HRMError("请选择要发放的工资记录")
                records = []
                for record_id in dict.fromkeys(ids):
                    row = self._record(conn, "payroll", record_id)
                    if row["month"] != month:
                        raise HRMError("选择的工资记录不属于该月份")
                    if row["status"] == "已发放":
                        raise HRMError("工资已发放，不能重复发放")
                    records.append(row)
            else:
                records = conn.execute("SELECT * FROM payroll WHERE month=? AND status='待发放'", (month,)).fetchall()
            if not records:
                raise HRMError("该月没有待发放工资，请先生成工资")
            paid_at = datetime.now().isoformat(timespec="seconds")
            for row in records:
                conn.execute("UPDATE payroll SET status='已发放',paid_at=? WHERE id=?", (paid_at, row["id"]))
                self._audit(conn, current, "发放工资", "payroll", row["id"], month)
            return {"count": len(records)}

    def export_csv(self, resource, filters, user):
        with self._connection() as conn:
            current = self._check(conn, user, resource)
            definition = RESOURCES[resource]
            columns = definition["columns"]
            labels = {f["name"]: f["label"] for f in definition["fields"]}
            for f in definition["fields"]:
                if f.get("reference"):
                    labels[f["name"][:-3] + "_name"] = f["label"]
            output = io.StringIO(newline="")
            writer = csv.writer(output)
            writer.writerow([labels.get(k, k) for k in columns])
            for row in self._rows(conn, resource, filters):
                if resource == "notices" and row["status"] != "已发布" and not self._allowed(current, resource, True):
                    continue
                values = []
                for key in columns:
                    value = row.get(key, "")
                    if isinstance(value, list):
                        value = "、".join(value)
                    value = "" if value is None else str(value)
                    if value.lstrip().startswith(("=", "+", "-", "@")):
                        value = "'" + value
                    values.append(value)
                writer.writerow(values)
            return output.getvalue()

    def audit(self, user):
        with self._connection() as conn:
            self._module_check(conn, user, "settings")
            return {"items": [dict(row) for row in conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 500")]}
