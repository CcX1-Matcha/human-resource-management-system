# 人力资源管理系统需求与设计

## 需求来源与范围

依据用户提供的《软件综合实践》文档第二节开发程序。实践考勤、课程评分、上传校友邦等是教学管理要求，不是程序业务功能，不自动执行。文档中系统设置的“社保比例”重复列出，合并为一项。

## 运行方式

Python 3.10+ 标准库 HTTP 服务、SQLite 持久化数据库、HTML/CSS/JavaScript 中文网页界面，无需安装第三方库或配置数据库。默认仅监听 127.0.0.1:8000，适配 Windows 10 和现代浏览器。提供 start.bat，源代码、示例数据、需求设计、操作和测试说明。金额使用 Decimal 计算后保留两位；演示工资为教学简化口径，不包含个税等文档未规定的政策。

## 功能

- 人事：员工档案增删改查、状态与离职日期、职工社保、奖罚、调动并同步组织、证书、实习生、请假审批、未来生日查询。
- 培训：课程、内部培训、一线工培训，关联课程、人员、日期、结果。
- 薪酬：薪酬级别、加班标准、水电费、加班、计件、计时工资。按月汇总与该月存在雇佣日期交集的员工，基本工资 + 加班 + 计件 + 计时 + 奖励 - 处罚 - 水电 - 个人社保 = 实发。基本工资不按月中入离职天数折算。已审批的无薪假按基本工资/21.75折算扣款，跨月记录按日历天比例分摊。社保按员工参保基数与配置个人费率计算，企业部分另记。生成、查看明细、逐项或批量发放；防止重复发放，已发放不重算。工资档案与发放在同一页。
- 公共查询：按姓名、工号、部门、状态查找员工；通知管理、打印。
- 报表：性别、学历、工龄、年龄、离职率、月度入职、月度离职、部门人员统计，支持导出。
- 设置：社保比例、导航菜单、角色、用户、模块权限、组织结构、数据字典。角色与模块权限在同一页。菜单名称、排序、显示立即生效，系统设置菜单保留以便恢复。字典类别“学历”与“假别”的启用记录分别补充员工/请假选项。管理员管理账号和权限；人事、薪酬专员和查询用户拥有不同权限，服务端强制校验。
- 通用：搜索、筛选、记录表单、删除确认、CSV 导出、明确错误提示、空状态、审计记录。

## 接口契约

所有 JSON 正常响应为直接对象，异常为 {error:中文说明}，使用恰当 HTTP 状态码。记录 id 为整数。

- POST /api/login {username,password} -> {user,csrf}; GET /api/session 同响应；POST /api/logout。会话 cookie HttpOnly SameSite=Strict；修改请求带 X-CSRF-Token。
- GET /api/meta -> {modules:[{id,title,icon}],resources:{key:{title,module,fields:[{name,label,type,required,options?,reference?,readonly?}],columns:[字段名]}},permissions:[{id,title}]}。
- GET /api/records/{key}?q=&department=&status= -> {items:[记录],total}; POST 创建；PUT /api/records/{key}/{id} 更新；DELETE 删除。记录包含字段原值及 employee_name、department_name 等显示关联值。
- GET /api/dashboard -> {metrics:{employees,departments,pending_leaves,monthly_payroll},department_counts:[{label,value}],recent_employees:[],upcoming_birthdays:[],notices:[],month:YYYY-MM}。
- GET /api/birthdays?days=30 -> {items:[员工含 next_birthday,days_until,age],total}。
- GET /api/reports?year=2026 -> {year,summary:{total,active,resigned,turnover_rate},gender:[{label,value}],education:[],age:[],tenure:[],departments:[],monthly:[{month,joined,resigned}]}。
- POST /api/payroll/generate {month:YYYY-MM} -> {items:[],count}; POST /api/payroll/pay {month,ids?:[]} -> {count}; GET /api/records/payroll?month=。
- GET /api/export/{key} CSV；GET /api/audit -> {items:[]}。
- user 为 {id,username,name,role,permissions:[模块id或 all]}。

## 服务代码接口

hrm.service.HRMService(db_path, seed=True) 提供 login(username,password), user(user_id), meta(user), list_records(resource,filters,user), create(resource,data,user), update(resource,id,data,user), delete(resource,id,user), dashboard(user), birthdays(days,user), reports(year,user), generate_payroll(month,user), pay_payroll(month,ids,user), export_csv(resource,filters,user), audit(user)。HRMError(message,status=400) 承载业务错误。每次操作使用独立数据库连接，线程安全；seed=False 仍初始化系统管理员和基础配置，但不放业务演示数据。

## 验收

真实数据库和 HTTP 测试覆盖登录、未授权读写、CSRF、员工重复工号、日期与关联校验、调动同步、请假审批、工资精确计算与锁定、防止重复发放、统计、CSV、重启持久化。浏览器实际检查登录、各模块导航、员工新增/编辑/查询、工资生成、通知打印视图与窄屏布局。
