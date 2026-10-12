"""Friendly fictitious sample data, inserted once per database."""
import json
from datetime import date, timedelta

from .schema import MODULES, RESOURCES


def insert(conn, resource, **data):
    values = {}
    for f in RESOURCES[resource]["fields"]:
        if f["type"] == "password":
            continue
        value = data.get(f["name"], f.get("default", None if f.get("reference") else ""))
        if f["type"] == "permissions" and isinstance(value, list):
            value = json.dumps(value, ensure_ascii=False)
        values[f["name"]] = value
    values.update({k: v for k, v in data.items() if k not in values})
    sql = f'INSERT INTO "{resource}" (' + ",".join(f'"{k}"' for k in values) + ") VALUES (" + ",".join("?" for _ in values) + ")"
    return conn.execute(sql, list(values.values())).lastrowid


def seed_base(conn, hash_password):
    if conn.execute("SELECT 1 FROM app_state WHERE key='base_initialized'").fetchone():
        return
    roles = [
        ("admin", "系统管理员", ["all"], "否", "Admin123!", "系统管理员"),
        ("hr", "人事专员", ["personnel", "training", "query", "reports"], "否", "Hr123456!", "人事专员"),
        ("payroll", "薪酬专员", ["payroll", "query", "reports"], "否", "Pay123456!", "薪酬专员"),
        ("viewer", "查询用户", ["query", "reports"], "是", "View123456!", "访客查询"),
    ]
    for code, name, permissions, readonly, password, display in roles:
        role = insert(conn, "roles", code=code, name=name, permissions=permissions, read_only=readonly, description="教学演示初始角色")
        insert(conn, "users", username=code, name=display, role_id=role, password_hash=hash_password(password), status="启用")
    departments = [("RD", "研发中心", "林知远"), ("HR", "人力资源部", "沈若宁"), ("FIN", "财务部", "许文清"), ("OPS", "运营部", "周知夏"), ("MFG", "生产车间", "赵明远")]
    for code, name, manager in departments:
        insert(conn, "departments", code=code, name=name, manager=manager, description="星河制造（虚构演示组织）")
    for name, salary in [("P1 · 初级", "5500"), ("P2 · 中级", "8500"), ("P3 · 高级", "12000")]:
        insert(conn, "salary_grades", name=name, base_salary=salary, description="建议薪资，员工档案工资可独立设置")
    for name, price in [("工作日加班", "50"), ("休息日加班", "80"), ("专项值班", "65")]:
        insert(conn, "overtime_rates", name=name, hourly_rate=price, description="教学示例标准，可按企业规则调整")
    insert(conn, "insurance_rates", name="统一社保方案", employee_rate="0.105", employer_rate="0.22", description="教学简化比例，可编辑；个人与企业部分分别计算")
    for index, module in enumerate(MODULES, 1):
        insert(conn, "menus", name=module["title"], module=module["id"], sort_order=str(index), visible="是")
    for index, (category, code, label) in enumerate([("学历", "bachelor", "本科"), ("学历", "master", "硕士"), ("职务", "engineer", "工程师"), ("职务", "specialist", "专员"), ("假别", "annual", "年假"), ("假别", "personal", "事假")], 1):
        insert(conn, "dictionaries", category=category, code=code, label=label, sort_order=str(index), status="启用")
    conn.execute("INSERT INTO app_state(key,value) VALUES('base_initialized','1')")


def seed_demo(conn):
    today = date.today()
    month = today.strftime("%Y-%m")
    first = today.replace(day=1)
    departments = [r[0] for r in conn.execute("SELECT id FROM departments ORDER BY id")]
    grades = [r[0] for r in conn.execute("SELECT id FROM salary_grades ORDER BY id")]
    rates = [r[0] for r in conn.execute("SELECT id FROM overtime_rates ORDER BY id")]
    names = ["林知远", "沈若宁", "许文清", "周知夏", "赵明远", "陈星河", "苏雨桐", "顾子安", "唐嘉禾", "陆书瑶", "方亦辰", "江映雪", "宋景行", "梁思齐", "温以宁", "何晨曦"]
    positions = ["研发工程师", "人事专员", "财务专员", "运营专员", "设备技术员"]
    employees = []
    for index, name in enumerate(names):
        department = departments[index % len(departments)]
        hire = today - timedelta(days=90 + index * 145)
        status = "离职" if index in (13, 15) else "试用" if index == 14 else "在职"
        birthday = (today + timedelta(days=3 + index * 4)).replace(year=1990 + index % 10).isoformat()
        employee = insert(conn, "employees", employee_no=f"XH{index + 1:04d}", name=name, gender="女" if index % 2 else "男", birthday=birthday, education=["本科", "硕士", "大专", "本科"][index % 4], department_id=department, position=positions[index % 5], hire_date=hire.isoformat(), status=status, resign_date=(today - timedelta(days=30 if index == 13 else 65)).isoformat() if status == "离职" else "", base_salary=str(5500 + index % 5 * 1250), salary_grade_id=grades[index % 3], phone=f"1380000{index:04d}", email=f"employee{index + 1}@example.com", notes="虚构演示员工，可直接编辑或新增业务记录")
        employees.append(employee)
        insert(conn, "social_insurance", employee_id=employee, base=str(5500 + index % 5 * 1250), start_date=hire.isoformat(), status="停保" if status == "离职" else "参保", end_date=(today - timedelta(days=30)).isoformat() if status == "离职" else "")
        if status != "离职":
            insert(conn, "utilities", employee_id=employee, month=month, water_fee=str(15 + index), electricity_fee=str(35 + index * 2), notes="员工宿舍月度费用")
            insert(conn, "overtime", employee_id=employee, month=month, rate_id=rates[index % 3], hours=str(2 + index % 4), notes="月度项目值班")
    courses = [
        insert(conn, "courses", name="新员工入职与制度说明", category="通用课程", instructor="沈若宁", hours="2", description="组织介绍、考勤制度和信息安全", status="启用"),
        insert(conn, "courses", name="生产安全与设备规范", category="安全培训", instructor="赵明远", hours="4", description="防护规范与操作演练", status="启用"),
        insert(conn, "courses", name="团队协作与沟通", category="能力提升", instructor="周知夏", hours="3", description="沟通方法与协同案例", status="启用"),
    ]
    for index in range(6):
        insert(conn, "internal_training", employee_id=employees[index], course_id=courses[index % 3], date=(today - timedelta(days=7 + index)).isoformat(), location="三楼培训室", score=str(85 + index), result="通过", notes="现场培训与考核")
    for index in (4, 9, 14):
        insert(conn, "frontline_training", employee_id=employees[index], course_id=courses[1], date=(today - timedelta(days=3)).isoformat(), workshop="一号车间", trainer="赵明远", result="通过", notes="安全操作演练")
        insert(conn, "piecework", employee_id=employees[index], month=month, description="成品装配", quantity=str(30 + index), unit_price="12.50")
        insert(conn, "hourly_work", employee_id=employees[index], month=month, description="设备保养", hours="4", hourly_rate="45")
    for index in range(3):
        insert(conn, "certificates", employee_id=employees[index], name=["专业技术资格证书", "人力资源管理师", "初级会计资格"][index], certificate_no=f"DEMO2026{index + 1:03d}", issued_date=(today - timedelta(days=400)).isoformat(), expiry_date=(today + timedelta(days=730)).isoformat(), issuer="虚构培训中心", notes="证书信息仅为演示")
        insert(conn, "rewards", employee_id=employees[index], date=(first + timedelta(days=1 + index)).isoformat(), kind="奖励" if index < 2 else "处罚", amount="300" if index < 2 else "50", reason="项目贡献" if index < 2 else "考勤迟到")
    leave_start = first + timedelta(days=4)
    insert(conn, "leaves", employee_id=employees[3], leave_type="年假", start_date=leave_start.isoformat(), end_date=(leave_start + timedelta(days=1)).isoformat(), days="2", paid="是", status="已批准", reason="家庭安排", approval_note="同意")
    insert(conn, "leaves", employee_id=employees[5], leave_type="事假", start_date=(first + timedelta(days=8)).isoformat(), end_date=(first + timedelta(days=8)).isoformat(), days="1", paid="否", status="已批准", reason="个人事务", approval_note="同意")
    insert(conn, "leaves", employee_id=employees[7], leave_type="病假", start_date=(today + timedelta(days=2)).isoformat(), end_date=(today + timedelta(days=2)).isoformat(), days="1", paid="是", status="待审批", reason="医院复诊")
    insert(conn, "interns", name="韩小满", school="星河理工大学（虚构）", major="软件工程", department_id=departments[0], start_date=(today - timedelta(days=35)).isoformat(), end_date=(today + timedelta(days=80)).isoformat(), mentor="林知远", status="实习中", phone="13900001234", notes="毕业实习")
    insert(conn, "interns", name="程予安", school="新辰职业学院（虚构）", major="机电一体化", department_id=departments[4], start_date=(today - timedelta(days=60)).isoformat(), end_date=(today + timedelta(days=60)).isoformat(), mentor="赵明远", status="实习中", phone="13900002345")
    insert(conn, "transfers", employee_id=employees[6], from_department_id=departments[1], from_position=positions[1], to_department_id=departments[3], transfer_date=(today - timedelta(days=20)).isoformat(), position="运营分析师", reason="跨部门培养")
    conn.execute("UPDATE employees SET department_id=?,position='运营分析师' WHERE id=?", (departments[3], employees[6]))
    insert(conn, "notices", title="欢迎使用星河人力资源管理系统", content="本系统覆盖人事、培训、薪酬、公共查询、统计报表与系统设置。所有人员和业务记录均为虚构教学示例。欢迎新增、编辑和查询记录。", date=today.isoformat(), author="人力资源部", status="已发布")
    insert(conn, "notices", title="本月培训安排与签到提醒", content="本月开展生产安全培训和团队协作课程，请各部门根据课程安排组织参加。培训结束后由人事专员登记成绩与结果。", date=(today - timedelta(days=2)).isoformat(), author="培训负责人", status="已发布")
    insert(conn, "notices", title="工资核对与发放说明", content="生成月度工资前，请核对加班、奖罚、水电费、社保及已审批请假。工资发放后明细锁定。当前薪资口径为教学简化示例。", date=(today - timedelta(days=4)).isoformat(), author="财务部", status="已发布")
