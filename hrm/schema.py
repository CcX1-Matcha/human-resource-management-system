"""Metadata shared by SQLite storage and the Chinese management interface."""

MODULES = [
    {"id": "personnel", "title": "人事管理", "icon": "users"},
    {"id": "training", "title": "培训管理", "icon": "book"},
    {"id": "payroll", "title": "薪酬管理", "icon": "wallet"},
    {"id": "query", "title": "公共查询", "icon": "search"},
    {"id": "reports", "title": "统计报表", "icon": "chart"},
    {"id": "settings", "title": "系统设置", "icon": "settings"},
]


def field(name, label, type="text", required=False, **kwargs):
    return {"name": name, "label": label, "type": type, "required": required, **kwargs}


def select(name, label, options, default=None, required=False):
    return field(name, label, "select", required, options=options, default=default or options[0])


def ref(name, label, resource, required=True):
    return field(name, label, "select", required, reference=resource)


def number(name, label, default="0", required=False, minimum="0", maximum=None, readonly=False):
    return field(name, label, "number", required, default=default, minimum=minimum, maximum=maximum, readonly=readonly)


def resource(title, module, fields, columns=None, **kwargs):
    return {"title": title, "module": module, "fields": fields, "columns": columns or [f["name"] for f in fields if f["type"] not in ("textarea", "password")][:7], **kwargs}


EMPLOYEE = ref("employee_id", "员工", "employees")
MONTH = field("month", "月份", "month", True)
NOTES = field("notes", "备注", "textarea")
RESOURCES = {
    "employees": resource("员工档案", "personnel", [
        field("employee_no", "工号", required=True), field("name", "姓名", required=True),
        select("gender", "性别", ["男", "女", "其他"]), field("birthday", "出生日期", "date"),
        select("education", "学历", ["高中", "中专", "大专", "本科", "硕士", "博士", "其他"], "本科"),
        ref("department_id", "部门", "departments"), field("position", "岗位"),
        field("hire_date", "入职日期", "date", True), select("status", "状态", ["在职", "试用", "离职"]),
        field("resign_date", "离职日期", "date"), number("base_salary", "基本工资（元）"),
        ref("salary_grade_id", "薪酬级别", "salary_grades", False), field("phone", "联系电话"), field("email", "邮箱", "email"), NOTES,
    ], ["employee_no", "name", "gender", "department_name", "position", "hire_date", "status", "base_salary"]),
    "social_insurance": resource("职工社保", "personnel", [EMPLOYEE, number("base", "参保基数（元）", required=True), field("start_date", "参保日期", "date", True), field("end_date", "结束日期", "date"), select("status", "状态", ["参保", "停保"]), NOTES], ["employee_name", "base", "start_date", "end_date", "status"]),
    "rewards": resource("奖罚记录", "personnel", [EMPLOYEE, field("date", "日期", "date", True), select("kind", "类型", ["奖励", "处罚"]), number("amount", "金额（元）", required=True), field("reason", "事由", "textarea", True)], ["employee_name", "date", "kind", "amount", "reason"]),
    "transfers": resource("员工调动", "personnel", [EMPLOYEE, ref("from_department_id", "原部门", "departments", False), ref("to_department_id", "调入部门", "departments"), field("transfer_date", "调动日期", "date", True), field("position", "调任岗位"), field("reason", "调动原因", "textarea")], ["employee_name", "from_department_name", "to_department_name", "transfer_date", "position"]),
    "certificates": resource("员工证书", "personnel", [EMPLOYEE, field("name", "证书名称", required=True), field("certificate_no", "证书编号"), field("issued_date", "颁发日期", "date", True), field("expiry_date", "到期日期", "date"), field("issuer", "发证机构"), NOTES], ["employee_name", "name", "certificate_no", "issued_date", "expiry_date", "issuer"]),
    "interns": resource("实习生管理", "personnel", [field("name", "姓名", required=True), field("school", "学校", required=True), field("major", "专业"), ref("department_id", "部门", "departments"), field("start_date", "开始日期", "date", True), field("end_date", "结束日期", "date"), field("mentor", "指导老师"), select("status", "状态", ["实习中", "已转正", "已结束"]), field("phone", "联系电话"), NOTES], ["name", "school", "department_name", "start_date", "end_date", "status"]),
    "leaves": resource("请假审批", "personnel", [EMPLOYEE, select("leave_type", "假别", ["事假", "病假", "年假", "婚假", "产假", "其他"]), field("start_date", "开始日期", "date", True), field("end_date", "结束日期", "date", True), number("days", "请假天数", "1", True, "0.01"), select("paid", "是否带薪", ["否", "是"]), select("status", "审批状态", ["待审批", "已批准", "已驳回"]), field("reason", "请假原因", "textarea", True), field("approval_note", "审批意见", "textarea")], ["employee_name", "leave_type", "start_date", "end_date", "days", "paid", "status"]),
    "courses": resource("课程管理", "training", [field("name", "课程名称", required=True), field("category", "课程类别"), field("instructor", "讲师", required=True), number("hours", "学时", "2", True, "0.01"), field("description", "课程内容", "textarea"), select("status", "状态", ["启用", "停用"])], ["name", "category", "instructor", "hours", "status"]),
    "internal_training": resource("内部培训", "training", [EMPLOYEE, ref("course_id", "课程", "courses"), field("date", "培训日期", "date", True), field("location", "地点"), number("score", "考核分数", "0", False, "0", "100"), select("result", "结果", ["待参加", "通过", "未通过"]), NOTES], ["employee_name", "course_name", "date", "location", "score", "result"]),
    "frontline_training": resource("一线工培训", "training", [EMPLOYEE, ref("course_id", "课程", "courses"), field("date", "培训日期", "date", True), field("workshop", "车间/地点"), field("trainer", "指导人"), select("result", "结果", ["待参加", "通过", "未通过"]), NOTES], ["employee_name", "course_name", "date", "workshop", "trainer", "result"]),
    "salary_grades": resource("薪酬级别", "payroll", [field("name", "级别名称", required=True), number("base_salary", "建议基本工资（元）", required=True), field("description", "说明", "textarea")]),
    "overtime_rates": resource("加班标准", "payroll", [field("name", "标准名称", required=True), number("hourly_rate", "每小时工资（元）", required=True), field("description", "说明", "textarea")]),
    "utilities": resource("水电费", "payroll", [EMPLOYEE, MONTH, number("water_fee", "水费（元）"), number("electricity_fee", "电费（元）"), NOTES], ["employee_name", "month", "water_fee", "electricity_fee"]),
    "overtime": resource("加班工资", "payroll", [EMPLOYEE, MONTH, ref("rate_id", "加班标准", "overtime_rates"), number("hours", "加班小时", required=True), NOTES], ["employee_name", "month", "rate_name", "hours"]),
    "piecework": resource("计件工资", "payroll", [EMPLOYEE, MONTH, field("description", "计件项目", required=True), number("quantity", "数量", required=True), number("unit_price", "单价（元）", required=True)], ["employee_name", "month", "description", "quantity", "unit_price"]),
    "hourly_work": resource("计时工资", "payroll", [EMPLOYEE, MONTH, field("description", "工作内容", required=True), number("hours", "小时数", required=True), number("hourly_rate", "时薪（元）", required=True)], ["employee_name", "month", "description", "hours", "hourly_rate"]),
    "payroll": resource("工资档案与发放", "payroll", [
        {**EMPLOYEE, "readonly": True}, {**MONTH, "readonly": True},
        *[number(name, label, readonly=True) for name, label in [
            ("base_salary", "基本工资"), ("overtime_pay", "加班工资"), ("piecework_pay", "计件工资"), ("hourly_pay", "计时工资"), ("reward_amount", "奖励"), ("penalty_amount", "处罚"), ("utility_deduction", "水电费"), ("employee_insurance", "个人社保"), ("employer_insurance", "企业社保"), ("leave_deduction", "无薪假扣款"), ("gross_salary", "应发工资"), ("total_deduction", "扣款合计"), ("net_salary", "实发工资")]],
        field("status", "发放状态", readonly=True), field("paid_at", "发放时间", readonly=True), NOTES,
    ], ["employee_name", "month", "base_salary", "gross_salary", "total_deduction", "net_salary", "status"]),
    "notices": resource("通知公告", "query", [field("title", "标题", required=True), field("content", "内容", "textarea", True), field("date", "发布日期", "date", True), field("author", "发布人"), select("status", "状态", ["已发布", "草稿"])], ["title", "date", "author", "status"]),
    "insurance_rates": resource("社保比例", "settings", [field("name", "方案名称", required=True), number("employee_rate", "个人比例（0~1）", "0.105", True, "0", "1"), number("employer_rate", "企业比例（0~1）", "0.22", True, "0", "1"), field("description", "说明", "textarea")]),
    "menus": resource("导航菜单", "settings", [field("name", "菜单名称", required=True), select("module", "所属模块", [m["id"] for m in MODULES]), number("sort_order", "顺序"), select("visible", "是否显示", ["是", "否"])]),
    "roles": resource("角色与权限", "settings", [field("code", "角色标识", required=True), field("name", "角色名称", required=True), field("permissions", "模块权限", "permissions", True, options=[{"value": "all", "label": "全部权限"}] + [{"value": m["id"], "label": m["title"]} for m in MODULES]), select("read_only", "只读角色", ["否", "是"]), field("description", "说明", "textarea")], ["code", "name", "permissions", "read_only"]),
    "users": resource("用户管理", "settings", [field("username", "登录账号", required=True), field("name", "显示名称", required=True), ref("role_id", "角色", "roles"), field("password", "密码（新增必填，编辑留空保持）", "password"), select("status", "状态", ["启用", "停用"])], ["username", "name", "role_name", "status"]),
    "departments": resource("组织结构", "settings", [field("code", "部门编码", required=True), field("name", "部门名称", required=True), ref("parent_id", "上级部门", "departments", False), field("manager", "负责人"), field("description", "说明", "textarea")], ["code", "name", "parent_name", "manager"]),
    "dictionaries": resource("数据字典", "settings", [field("category", "字典类别", required=True), field("code", "值编码", required=True), field("label", "显示名称", required=True), number("sort_order", "顺序"), select("status", "状态", ["启用", "停用"])], ["category", "code", "label", "sort_order", "status"]),
}

UNIQUE = {"employees": [("employee_no",)], "users": [("username",)], "roles": [("code",)], "departments": [("code",)], "salary_grades": [("name",)], "overtime_rates": [("name",)], "social_insurance": [("employee_id",)], "payroll": [("employee_id", "month")], "insurance_rates": [("name",)], "dictionaries": [("category", "code")]}


def create_tables(conn):
    for key, definition in RESOURCES.items():
        parts = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
        for f in definition["fields"]:
            if f["type"] == "password":
                continue
            name = f["name"]
            sql_type = "INTEGER" if f.get("reference") else "TEXT"
            part = f'"{name}" {sql_type}'
            if f.get("reference"):
                part += f' REFERENCES "{f["reference"]}"(id) ON DELETE RESTRICT'
            parts.append(part)
        if key == "users":
            parts.append("password_hash TEXT NOT NULL")
        if key == "transfers":
            parts.append("from_position TEXT")
        parts.extend("UNIQUE (" + ",".join(f'"{f}"' for f in fields) + ")" for fields in UNIQUE.get(key, []))
        conn.execute(f'CREATE TABLE IF NOT EXISTS "{key}" (' + ",".join(parts) + ")")
        if key == "transfers" and "from_position" not in {r[1] for r in conn.execute('PRAGMA table_info("transfers")')}:
            conn.execute('ALTER TABLE transfers ADD COLUMN from_position TEXT')
    conn.execute("CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, action TEXT, resource TEXT, record_id INTEGER, detail TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
