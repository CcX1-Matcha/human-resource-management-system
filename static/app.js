/* Native browser application. Shared pure helpers are also checked with Node. */
(function () {
  'use strict';

  function escapeHTML(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  }
  function optionList(options) {
    return (options || []).map(item => typeof item === 'object' && item !== null ? {value:item.value == null ? item.id : item.value, label:item.label == null ? (item.title || item.name || item.value) : item.label} : {value:item,label:item});
  }
  function displayValue(record, field) {
    const value = record[field.name];
    if (field.reference) {
      const related = field.name.replace(/_id$/, '') + '_name';
      if (record[related] != null) return record[related];
      if (field.name === 'employee_id' && record.employee_name) return record.employee_name;
    }
    if (Array.isArray(value)) return value.join('、');
    if (field.options) {
      const found = optionList(field.options).find(option => String(option.value) === String(value));
      if (found) return found.label;
    }
    if (field.type === 'boolean' || field.type === 'checkbox') return value ? '是' : '否';
    if (value == null || value === '') return '—';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }
  function isMultiple(field) { return ['multiselect','permissions','array'].includes(field.type) || field.name === 'permissions'; }
  function collectForm(form, fields, editing) {
    const data = {};
    const elements = Array.from(form.elements);
    fields.forEach(field => {
      if (field.readonly || (editing && field.type === 'password' && !elements.find(e => e.name === field.name)?.value)) return;
      const controls = elements.filter(e => e.name === field.name);
      if (!controls.length) return;
      if (isMultiple(field)) {
        data[field.name] = controls.filter(e => e.checked || e.selected).map(e => e.value);
      } else if (field.type === 'boolean' || field.type === 'checkbox') {
        data[field.name] = !!controls[0].checked;
      } else {
        let value = field.type === 'password' ? controls[0].value : controls[0].value.trim();
        if (value && (field.reference || ['integer','number','money','decimal'].includes(field.type))) {
          if (Number.isFinite(Number(value))) value = Number(value);
        }
        data[field.name] = value === '' && field.reference ? null : value;
      }
    });
    return data;
  }
  function makeQuery(values) {
    const params = new URLSearchParams();
    Object.entries(values || {}).forEach(([key,value]) => { if (value !== '' && value !== null && value !== undefined) params.set(key,String(value)); });
    return params.size ? '?' + params.toString() : '';
  }
  function csvCell(value) {
    let text=String(value ?? '');
    if(typeof value!=='number' && /^[=+\-@]/.test(text.trimStart()))text="'"+text;
    return '"'+text.replaceAll('"','""')+'"';
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {escapeHTML,optionList,displayValue,collectForm,makeQuery,csvCell};
  if (typeof document === 'undefined') return;

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const esc = escapeHTML;
  const state = {user:null,csrf:'',meta:null,route:'',records:[],refs:{},page:1,pageSize:15,selected:new Set(),filters:{},loadId:0};
  const app = $('#app');
  const recordDialog = $('#record-dialog');
  const confirmDialog = $('#confirm-dialog');
  const colors = ['#7f9668','#b2c39a','#d8ddbb','#b6ab86','#7e9a92','#d0bea1','#96a478','#bdcfb4'];
  const icons = {
    logo:'<path d="M5 17V7l7-4 7 4v10l-7 4z"/><path d="m5 7 7 4 7-4M12 11v10"/><path d="m8 5 8 4"/>',
    home:'<path d="m3 10 9-7 9 7M5 9v11h14V9M9 20v-7h6v7"/>',
    people:'<circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 4a3 3 0 0 1 0 6M17 14a5 5 0 0 1 4 5v2"/>',
    book:'<path d="M12 6c-3-2-6-3-10-2v15c4-1 7 0 10 2 3-2 6-3 10-2V4c-4-1-7 0-10 2zM12 6v15"/>',
    wallet:'<path d="M3 7V5a2 2 0 0 1 2-2h13v4M3 7h17a1 1 0 0 1 1 1v12H5a2 2 0 0 1-2-2V7zM21 11h-6v5h6"/><path d="M17 13.5h.1"/>',
    search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    chart:'<path d="M4 3v18h17M8 16v-5M13 16V6M18 16v-8"/>',
    settings:'<path d="m9 3-1 3-3 1-2 3 2 2-1 4 3 2 3-1 3 2 3-2v-3l3-2-1-4-3-1-1-3z"/><circle cx="11" cy="11" r="3"/>',
    chevron:'<path d="m9 5 7 7-7 7"/>',
    plus:'<path d="M12 5v14M5 12h14"/>',
    download:'<path d="M12 3v12m-5-5 5 5 5-5M4 15v5h16v-5"/>',
    edit:'<path d="m15 4 5 5M4 20l1-6L16 3a2 2 0 0 1 3 0l2 2a2 2 0 0 1 0 3L10 19zM4 20l6-1"/>',
    trash:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
    close:'<path d="m6 6 12 12M18 6 6 18"/>',
    arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
    check:'<path d="m5 12 4 4L19 6"/>',
    info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
    alert:'<path d="m12 3 10 18H2zM12 9v5M12 17h.01"/>',
    building:'<path d="M5 21V3h14v18M2 21h20M9 7h.01M15 7h.01M9 11h.01M15 11h.01M9 15h.01M15 15h.01M10 21v-3h4v3"/>',
    calendar:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 11h18M8 15h.01M12 15h.01M16 15h.01"/>',
    gift:'<path d="M3 9h18v4H3zM5 13v8h14v-8M12 9v12"/><path d="M12 9s-8 0-7-4 7 0 7 4c0-4 6-8 7-4s-7 4-7 4z"/>',
    bell:'<path d="M6 8a6 6 0 0 1 12 0c0 7 3 8 3 8H3s3-1 3-8M9 20h6"/>',
    print:'<path d="M6 8V3h12v5M6 16H3V8h18v8h-3M6 13h12v8H6zM17 10h.01"/>',
    logout:'<path d="M9 4H4v16h5M9 12h12m-5-5 5 5-5 5"/>',
    shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8 12l3 3 5-6"/>',
    menu:'<path d="M3 6h18M3 12h18M3 18h18"/>',
    eye:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    refresh:'<path d="M20 7V3l-3 3a8 8 0 1 0 3 8M20 3h-5"/>',
    clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    document:'<path d="M5 3h9l5 5v13H5zM14 3v5h5M8 12h8M8 16h8"/>',
    lock:'<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4M12 14v3"/>',
    spark:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/>'
  };
  function icon(name, className = '') { return '<svg aria-hidden="true" viewBox="0 0 24 24" class="icon '+esc(className)+'">'+(icons[name] || icons.document)+'</svg>'; }
  function localISO(date = new Date()) { return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`; }
  function thisMonth() { return localISO().slice(0,7); }
  function currency(value) { return Number(value || 0).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}); }
  function shortDate(value) { return value ? String(value).slice(0,10).replaceAll('-','.') : '—'; }
  function hasPermission(moduleId) { return !!state.user && (state.user.permissions || []).some(p => p === 'all' || p === moduleId); }
  function resourceMeta(key) { return state.meta?.resources?.[key]; }
  function roleName() { const role = state.user.role; return typeof role === 'object' ? (role.name || role.title) : ({admin:'系统管理员',hr:'人事专员',personnel:'人事专员',payroll:'薪酬专员',viewer:'查询用户',query:'查询用户'}[role] || role || '员工用户'); }
  function moduleKind(module) {
    if (['personnel','training','payroll','query','reports','settings'].includes(module.id)) return module.id;
    const title = module.title || '';
    if (/人事/.test(title)) return 'personnel';
    if (/培训/.test(title)) return 'training';
    if (/薪|工资/.test(title)) return 'payroll';
    if (/报表|统计/.test(title)) return 'reports';
    if (/设置/.test(title)) return 'settings';
    if (/查询|公共/.test(title)) return 'query';
    return module.id;
  }
  function moduleIcon(module) { return {personnel:'people',training:'book',payroll:'wallet',query:'search',reports:'chart',settings:'settings'}[moduleKind(module)] || module.icon || 'document'; }
  function moduleByKind(kind) { return (state.meta?.modules || []).find(m => moduleKind(m) === kind); }
  function canKind(kind) { const module = moduleByKind(kind); return !!module && hasPermission(module.id); }
  function isReadonly(key) { return key === 'payroll' || resourceMeta(key)?.can_write === false || !!resourceMeta(key)?.readonly || (key === 'employees' && state.route.startsWith('query/')); }
  function toast(message, error = false) {
    const item = document.createElement('div');
    item.className = 'toast' + (error ? ' error' : '');
    item.innerHTML = icon(error ? 'alert' : 'check')+'<span>'+esc(message)+'</span>';
    const region=$('#toast-region');
    while(region.children.length>=3)region.firstElementChild.remove();
    region.append(item);
    setTimeout(() => { item.classList.add('fading');setTimeout(() => item.remove(),250); },error ? 6500 : 3500);
  }
  async function api(path, options = {}) {
    const request = {method:options.method || 'GET',credentials:'same-origin',headers:{Accept:'application/json'}};
    if (request.method !== 'GET') request.headers['X-CSRF-Token'] = state.csrf;
    if (options.body !== undefined) { request.headers['Content-Type']='application/json';request.body=JSON.stringify(options.body); }
    let response;
    try { response = await fetch('/api'+path,request); }
    catch (_) { throw new Error('无法连接服务，请确认程序仍在运行，然后重试。'); }
    let result;
    try { result = await response.json(); }
    catch (_) { throw new Error('服务返回了无法读取的数据，请重试。'); }
    if (!response.ok) {
      const error = new Error(result.error || '操作未完成，请重试。');
      error.status = response.status;
      if (response.status === 401 && state.user && path !== '/login') { state.user=null;state.meta=null;state.refs={};recordDialog.close();showLogin('登录已过期，请重新登录。'); }
      throw error;
    }
    return result;
  }
  function errorBox(message) { return '<div class="error-box" role="alert">'+icon('alert')+'<span>'+esc(message)+'</span></div>'; }
  function emptyState(title='暂无记录', message='新增第一条记录，开始管理。', action='') { return '<div class="empty-state"><div class="empty-illustration">'+icon('document')+'</div><h3>'+esc(title)+'</h3><p>'+esc(message)+'</p>'+action+'</div>'; }
  function loading() { return '<div class="loading-panel"><span class="spinner"></span>正在加载数据…</div>'; }
  function pageFooter() { return '<footer class="page-footer"><span>'+icon('shield')+'知人 · 人力资源管理</span><span>让每一份人才价值，被看见。</span></footer>'; }
  function setPageHeading(title, description='', actions='', overline='') {
    return '<header class="page-heading"><div>'+(overline?'<div class="overline">'+esc(overline)+'</div>':'')+'<h1>'+esc(title)+'</h1>'+(description?'<p>'+esc(description)+'</p>':'')+'</div><div class="heading-actions">'+actions+'</div></header>';
  }
  function navigate(route) { location.hash = '/'+route; if (state.route === route) loadRoute(); }
  function statusBadge(value) {
    const text = String(value == null ? '—' : value);
    const lower = text.toLowerCase();
    const tone = /拒|驳回|处罚|离职|停用|disabled|rejected|resigned|inactive/.test(lower) ? 'red' : /待|未|pending|unpaid/.test(lower) ? 'amber' : /结束|失效|取消|completed|cancelled/.test(lower) ? 'gray' : '';
    return '<span class="badge '+tone+'">'+esc(text)+'</span>';
  }

  function showLogin(message = '') {
    state.route='';
    app.innerHTML = '<main class="login-page"><aside class="login-brand"><div class="brand-lockup"><div class="brand-mark">'+icon('logo')+'</div><div><div class="brand-name">知人</div><div class="brand-subtitle">PEOPLE & POSSIBILITY</div></div></div><div class="login-message"><div class="overline">PEOPLE FIRST, ALWAYS</div><h1>让人才的每一步，<br>都有温度。</h1><p>从人员档案到薪酬发放，用清晰有序的管理，连接团队与成长。</p><div class="login-feature-list"><span>'+icon('people')+'人员管理</span><span>'+icon('wallet')+'薪酬核算</span><span>'+icon('chart')+'数据洞察</span></div></div><div class="login-orbit"></div><div class="brand-footer">知人 · 人力资源管理工作台</div></aside><section class="login-side"><div class="login-card"><h2>欢迎回来</h2><p>登录账户，开启今天的工作。</p><div id="login-error">'+(message ? errorBox(message) : '')+'</div><form id="login-form"><div class="field"><label for="username">用户名</label><input id="username" name="username" autocomplete="username" placeholder="请输入用户名" required maxlength="100" value="admin"></div><div class="field"><label for="password">密码</label><input id="password" name="password" type="password" autocomplete="current-password" placeholder="请输入密码" required maxlength="200"></div><button class="button primary" type="submit">登录工作台 '+icon('arrow')+'</button></form><div class="login-help">初次使用请查看项目使用说明中的演示账户。<br>由管理员为员工分配账户与访问权限。</div><div class="login-divider"></div><div class="login-security">'+icon('shield')+'本地运行 · 数据保存在本机</div></div></section></main>';
    $('#login-form').addEventListener('submit', async event => {
      event.preventDefault();
      const button = $('button[type=submit]',event.target);
      button.disabled=true;button.innerHTML='<span class="spinner"></span> 正在登录';$('#login-error').innerHTML='';
      try {
        const session = await api('/login',{method:'POST',body:{username:$('#username').value.trim(),password:$('#password').value}});
        await startSession(session);
      } catch (error) { $('#login-error').innerHTML=errorBox(error.message);button.disabled=false;button.innerHTML='登录工作台 '+icon('arrow'); }
    });
  }
  async function startSession(session) {
    state.user=session.user;state.csrf=session.csrf;state.refs={};
    state.meta=await api('/meta');
    renderShell();
    await loadRoute();
  }
  function renderShell() {
    const date = new Date().toLocaleDateString('zh-CN',{year:'numeric',month:'long',day:'numeric',weekday:'short'});
    app.innerHTML = '<div class="app-shell"><aside class="sidebar"><a class="brand-lockup" href="#/dashboard" aria-label="知人工作台"><div class="brand-mark">'+icon('logo')+'</div><div><div class="brand-name">知人</div><div class="brand-subtitle">HR MANAGEMENT</div></div></a><nav aria-label="主导航" id="main-nav"></nav><div class="sidebar-bottom"><div><span class="online-dot"></span>系统运行正常</div><span>人才有序 · 成长有迹</span></div></aside><div class="sidebar-backdrop" data-close-nav></div><div class="main-shell"><header class="topbar"><div class="topbar-left"><button class="icon-button mobile-toggle" aria-label="展开导航" data-toggle-nav>'+icon('menu')+'</button><div class="breadcrumb" id="breadcrumb">'+icon('home')+'<span>工作台</span></div></div><div class="topbar-right"><span class="topbar-date">'+esc(date)+'</span><div class="user-block"><div class="avatar">'+esc((state.user.name || state.user.username || '用').slice(0,1))+'</div><div><div class="user-name">'+esc(state.user.name || state.user.username)+'</div><div class="user-role">'+esc(roleName())+'</div></div></div><button class="icon-button" title="退出登录" aria-label="退出登录" id="logout-button">'+icon('logout')+'</button></div></header><main class="page" id="page-content" tabindex="-1"></main></div></div>';
    $('[data-toggle-nav]').addEventListener('click',() => $('.app-shell').classList.toggle('nav-open'));
    $('[data-close-nav]').addEventListener('click',() => $('.app-shell').classList.remove('nav-open'));
    $('#logout-button').addEventListener('click',async () => {
      if (!await confirmAction('退出登录','退出后需要重新输入账户和密码。','退出登录')) return;
      try { await api('/logout',{method:'POST'});state.user=null;state.meta=null;state.csrf='';state.refs={};location.hash='/dashboard';showLogin(); }
      catch (error) { toast(error.message,true); }
    });
    renderNav();
  }
  function renderNav() {
    const route = state.route;
    let html = '<div class="nav-label">WORKSPACE / 工作空间</div><a class="nav-link '+(route==='dashboard'?'active':'')+'" href="#/dashboard">'+icon('home')+'<span>工作台概览</span></a><div class="nav-label" style="margin-top:24px">MANAGEMENT / 业务管理</div>';
    (state.meta.modules || []).forEach(module => {
      if (!hasPermission(module.id)) return;
      const kind = moduleKind(module);
      const resources = Object.entries(state.meta.resources).filter(([,resource])=>resource.module===module.id && resource.can_read !== false);
      const links = resources.map(([key,resource])=>({route:'records/'+key,title:resource.title}));
      if (kind==='personnel') links.push({route:'birthdays',title:'员工生日'});
      if (kind==='query') links.unshift({route:'query/employees',title:'员工公共查询'});
      if (kind==='reports') links.unshift({route:'reports',title:'人事统计报表'});
      if (kind==='settings') links.push({route:'audit',title:'操作日志'});
      if (!links.length) return;
      const selected = links.some(link=>link.route===route);
      const target = links[0].route;
      html += '<button class="nav-link nav-module '+(selected?'active':'')+'" data-module="'+esc(module.id)+'" data-first="'+esc(target)+'" aria-expanded="'+selected+'">'+icon(moduleIcon(module))+'<span>'+esc(module.title)+'</span>'+icon('chevron','chevron')+'</button><div class="nav-children" data-children="'+esc(module.id)+'" '+(selected?'':'hidden')+'>'+links.map(link=>'<a class="nav-child '+(route===link.route?'active':'')+'" href="#/'+esc(link.route)+'">'+esc(link.title)+'</a>').join('')+'</div>';
    });
    $('#main-nav').innerHTML=html;
    $$('.nav-module').forEach(button=>button.addEventListener('click',()=>{
      const children=$$('[data-children]').find(node=>node.dataset.children===button.dataset.module);
      const expanded=button.getAttribute('aria-expanded')==='true';
      button.setAttribute('aria-expanded',String(!expanded));children.hidden=expanded;
      if (!expanded && !button.classList.contains('active')) navigate(button.dataset.first);
    }));
    $$('#main-nav a').forEach(link=>link.addEventListener('click',()=>$('.app-shell').classList.remove('nav-open')));
  }
  async function loadRoute() {
    if (!state.user || !state.meta) return;
    const route = decodeURIComponent(location.hash.replace(/^#\/?/,'') || 'dashboard');
    const changed=route!==state.route;
    state.route=route;
    if (changed) { state.page=1;state.filters={};state.selected.clear(); }
    const loadId=++state.loadId;
    renderNav();
    const page=$('#page-content');
    page.innerHTML=loading();
    try {
      if (route==='dashboard') await renderDashboard(loadId);
      else if (route==='birthdays') await renderBirthdays(loadId);
      else if (route==='reports') await renderReports(loadId);
      else if (route==='audit') await renderAudit(loadId);
      else if (route.startsWith('records/') || route==='query/employees') await renderRecords(route==='query/employees'?'employees':route.slice(8),loadId);
      else { page.innerHTML=setPageHeading('页面未找到','请通过左侧导航选择业务页面。')+emptyState('页面不存在','可以返回工作台查看概览。','<a class="button primary" href="#/dashboard">返回工作台</a>'); }
    } catch (error) {
      if (state.loadId!==loadId || !state.user) return;
      page.innerHTML=setPageHeading('页面暂时无法加载','请检查权限或连接后重试。')+errorBox(error.message)+'<button class="button secondary" id="reload-page">'+icon('refresh')+'重新加载</button>';
      $('#reload-page').addEventListener('click',loadRoute);
    }
  }
  function setBreadcrumb(section, title) { $('#breadcrumb').innerHTML=icon('home')+'<a href="#/dashboard">工作台</a>'+icon('chevron')+'<span>'+esc(section)+'</span>'+(title && title!==section ? icon('chevron')+'<strong>'+esc(title)+'</strong>' : ''); }
  function activeLoad(loadId) { return loadId===state.loadId && !!state.user; }

  async function renderDashboard(loadId) {
    const data=await api('/dashboard');if(!activeLoad(loadId))return;
    setBreadcrumb('工作台概览');
    const metrics=data.metrics || {};
    const greeting = new Date().getHours()<12 ? '上午好' : new Date().getHours()<18 ? '下午好' : '晚上好';
    const cards=[{title:'在职员工',value:metrics.employees,unit:'人',icon:'people',note:'组织中每一份成长的力量'}, {title:'组织部门',value:metrics.departments,unit:'个',icon:'building',note:'协作有序，目标一致'}, {title:'待审批请假',value:metrics.pending_leaves,unit:'条',icon:'calendar',note:'及时处理，安心工作'}, {title:'本月实发薪酬',value:currency(metrics.monthly_payroll),unit:'元',icon:'wallet',note:(data.month || thisMonth())+' 月度核算'}];
    const quick=[];
    if(resourceMeta('employees')&&canKind('personnel'))quick.push({label:'新增员工',icon:'people',action:'new-employee'});
    if(resourceMeta('leaves')&&canKind('personnel'))quick.push({label:'请假审批',icon:'calendar',route:'records/leaves'});
    if(resourceMeta('payroll')&&canKind('payroll'))quick.push({label:'薪酬核算',icon:'wallet',route:'records/payroll'});
    if(canKind('reports'))quick.push({label:'人事报表',icon:'chart',route:'reports'});
    if(quick.length<4&&resourceMeta('notices'))quick.push({label:'公司通知',icon:'bell',route:'records/notices'});
    if(quick.length<4&&canKind('personnel'))quick.push({label:'员工生日',icon:'gift',route:'birthdays'});
    const departments=data.department_counts || [];
    const recent=data.recent_employees || [];
    const notices=data.notices || [];
    const birthdays=data.upcoming_birthdays || [];
    const page=$('#page-content');
    page.innerHTML=setPageHeading(greeting+'，'+(state.user.name || state.user.username)+' ☀','这里是团队的今日动态。让每一项人事工作，都井然有序。','<button class="button secondary" id="refresh-dashboard">'+icon('refresh')+'刷新概览</button>','YOUR PEOPLE, AT A GLANCE')+'<div class="metrics-grid">'+cards.map(card=>'<article class="metric-card"><div class="metric-header"><span>'+esc(card.title)+'</span><span class="metric-icon">'+icon(card.icon)+'</span></div><div class="metric-value">'+esc(card.value == null?'—':card.value)+'<span class="metric-unit">'+card.unit+'</span></div><div class="metric-note">'+icon('check')+esc(card.note)+'</div></article>').join('')+'</div><div class="dashboard-grid"><section class="panel"><div class="panel-head"><div><h2>人员分布</h2><p>在职员工的部门构成</p></div><span class="badge">实时数据</span></div><div class="panel-body">'+donutChart(departments)+'</div></section><div class="dashboard-right"><section class="panel"><div class="panel-head"><div><h2>快捷工作</h2><p>常用操作，触手可及</p></div>'+icon('spark')+'</div><div class="panel-body quick-actions" style="grid-template-columns:repeat('+Math.min(quick.length||1,4)+',1fr)">'+(quick.length?quick.slice(0,4).map(item=>'<button class="quick-card" '+(item.route?'data-route="'+esc(item.route)+'"':'data-action="'+esc(item.action)+'"')+'>'+icon(item.icon)+'<span>'+esc(item.label)+'</span></button>').join(''):'<p class="muted">通过左侧导航访问已授权模块。</p>')+'</div></section><section class="panel"><div class="panel-head"><div><h2>公司通知</h2><p>值得关注的新消息</p></div>'+(resourceMeta('notices')?'<a class="text-button" href="#/records/notices">全部通知 '+icon('chevron')+'</a>':'')+'</div><div class="panel-body notice-list">'+(notices.length?notices.slice(0,3).map(notice=>'<div class="notice-item"><div class="notice-symbol">'+icon('bell')+'</div><div class="notice-text"><h3>'+esc(notice.title || notice.name || '公司通知')+'</h3><p>'+esc(shortDate(notice.publish_date || notice.date || notice.created_at))+' · '+esc(notice.publisher || notice.author || '人事行政')+'</p></div><button class="text-button" data-notice="'+esc(notice.id)+'" style="font-size:10px">查看</button></div>').join(''):emptyState('暂无通知','新的公司通知会显示在这里。'))+'</div></section></div><section class="panel"><div class="panel-head"><div><h2>最近加入的同事</h2><p>欢迎新伙伴，一起向前</p></div>'+(resourceMeta('employees')?'<a class="text-button" href="#/'+(canKind('personnel')?'records/employees':'query/employees')+'">查看员工 '+icon('chevron')+'</a>':'')+'</div><div class="table-scroll">'+(recent.length?'<table class="recent-table"><thead><tr><th>员工</th><th>所属部门</th><th>岗位</th><th>入职日期</th><th>状态</th></tr></thead><tbody>'+recent.slice(0,5).map(employee=>'<tr><td><div class="employee-cell"><div class="avatar">'+esc((employee.name||'员').slice(0,1))+'</div><div><span>'+esc(employee.name)+'</span><small>'+esc(employee.employee_no || employee.code || '')+'</small></div></div></td><td>'+esc(employee.department_name || '—')+'</td><td>'+esc(employee.position || employee.job_title || '—')+'</td><td>'+esc(shortDate(employee.hire_date || employee.join_date))+'</td><td>'+statusBadge(employee.status || '在职')+'</td></tr>').join('')+'</tbody></table>':emptyState('欢迎第一位同事','新增员工后，这里将展示最新入职动态。'))+'</div></section><section class="panel"><div class="panel-head"><div><h2>即将到来的生日</h2><p>未来 30 天，一起分享喜悦</p></div>'+(canKind('personnel')?'<a class="text-button" href="#/birthdays">生日名单 '+icon('chevron')+'</a>':icon('gift'))+'</div><div class="panel-body birthday-list">'+(birthdays.length?birthdays.slice(0,4).map(employee=>'<div class="birthday-item"><div class="birthday-avatar">'+esc((employee.name||'员').slice(0,1))+'</div><div><strong>'+esc(employee.name)+'</strong><p>'+esc(employee.department_name || '同事')+'</p></div><div class="birthday-when">'+esc(employee.next_birthday ? shortDate(employee.next_birthday).slice(5) : shortDate(employee.birthday || employee.birth_date).slice(5))+'<small>'+esc(Number(employee.days_until)===0?'今天生日':employee.days_until+' 天后')+'</small></div></div>').join(''):emptyState('近期没有生日','每一次成长，都值得被记得。'))+'</div></section></div>'+pageFooter();
    $('#refresh-dashboard').addEventListener('click',loadRoute);
    const grid=$('.dashboard-grid',page);
    const [departmentPanel,rightColumn,recentPanel,birthdayPanel]=Array.from(grid.children);
    const leftColumn=document.createElement('div');leftColumn.className='dashboard-left';
    grid.insertBefore(leftColumn,departmentPanel);leftColumn.append(departmentPanel,recentPanel);rightColumn.append(birthdayPanel);
    $$('[data-route]',page).forEach(button=>button.addEventListener('click',()=>navigate(button.dataset.route)));
    $('[data-action="new-employee"]',page)?.addEventListener('click',()=>openRecordForm('employees'));
    $$('[data-notice]',page).forEach(button=>button.addEventListener('click',()=>openNotice(notices.find(n=>String(n.id)===button.dataset.notice))));
  }
  function donutChart(items) {
    if (!items.length || !items.some(item=>Number(item.value)>0)) return emptyState('暂无人员统计','新增在职员工并配置部门后即可查看。');
    const total=items.reduce((sum,item)=>sum+Number(item.value||0),0);
    let angle=0;const segments=items.map((item,i)=>{const start=angle;angle+=Number(item.value||0)/total*100;return colors[i%colors.length]+' '+start+'% '+angle+'%';});
    return '<div class="dept-chart"><div class="donut" role="img" aria-label="'+esc(items.map(item=>item.label+' '+item.value+' 人').join('，'))+'" style="background:conic-gradient('+segments.join(',')+')"><div class="donut-center"><strong>'+total+'</strong>在职员工</div></div><div class="chart-legend">'+items.map((item,i)=>'<div class="legend-item"><span class="legend-dot" style="background:'+colors[i%colors.length]+'"></span><span>'+esc(item.label)+'</span><strong>'+esc(item.value)+' 人</strong><small>'+Math.round(Number(item.value)/total*100)+'%</small></div>').join('')+'</div></div>';
  }

  async function loadReferences(fields) {
    const keys=[...new Set(fields.filter(field=>field.reference).map(field=>typeof field.reference==='string'?field.reference:field.reference.resource))];
    const results=await Promise.allSettled(keys.map(async key=> {
      if (!state.refs[key]) state.refs[key]=(await api('/records/'+encodeURIComponent(key))).items || [];
      return key;
    }));
    return results.map((result,i)=>result.status==='rejected'?keys[i]:null).filter(Boolean);
  }
  function referenceOptions(field) {
    const key=typeof field.reference==='string'?field.reference:field.reference.resource;
    return (state.refs[key] || []).map(record=>({value:record.id,label:record.name || record.title || record.label || record.username || record.code || '#'+record.id,record})).map(option=>({value:option.value,label:option.record.employee_no ? option.label+' · '+option.record.employee_no : option.label}));
  }
  function resourceDescription(key) {
    return {
      employees:'集中管理员工档案，掌握入职、组织归属与在职状态。',
      insurance:'维护员工参保基数，个人与企业缴费将用于月度薪酬核算。',
      social_insurance:'维护员工参保基数，个人与企业缴费将用于月度薪酬核算。',
      rewards:'记录员工奖罚，关联月份的金额将自动计入工资。',
      transfers:'记录岗位与部门调动，保存后同步更新员工所属组织。',
      certificates:'管理专业资质与证书，让员工能力一目了然。',
      interns:'记录实习人员、培养安排与实习周期。',
      leaves:'管理请假申请与审批，无薪假在获批后计入当月工资扣款。',
      courses:'整理培训课程，为团队提供持续成长的机会。',
      payroll:'汇总员工的月度收入与扣款，核对后发放工资。',
      salary_grades:'配置薪酬级别和基本工资参考标准。',
      overtime_rates:'设置加班计费标准，供员工加班记录关联使用。',
      notices:'发布公司通知，查看内容或打印为纸质公告。',
      roles:'为不同职责配置模块访问权限，权限校验由服务端执行。',
      users:'管理登录账户与角色。编辑时留空密码则保留当前密码。',
      permissions:'配置模块权限，明确不同角色的访问范围。',
      departments:'构建部门层级，连接人员档案与组织统计。',
      dictionaries:'维护业务字典，统一系统中使用的分类与名称。',
      menus:'配置导航菜单与显示顺序。',
      insurance_rates:'设置个人和企业社保费率，用于工资生成时的计算。'
    }[key] || '查询、维护业务记录，让日常管理清晰有序。';
  }
  async function renderRecords(key, loadId) {
    const meta=resourceMeta(key);
    if (!meta) throw new Error('当前账户无权访问此业务页面。');
    const filters={...state.filters};
    if (key==='payroll') filters.month=filters.month || thisMonth();
    state.filters=filters;
    const data=await api('/records/'+encodeURIComponent(key)+makeQuery(filters));
    if(!activeLoad(loadId))return;
    state.records=data.items || [];state.selected.clear();
    const module=(state.meta.modules || []).find(module=>module.id===meta.module);
    setBreadcrumb(state.route.startsWith('query/')?'公共查询':module?.title || '业务管理',meta.title);
    const hasDepartment=(meta.fields || []).some(field=>field.name==='department_id') || key==='employees';
    const departmentField=(meta.fields || []).find(field=>field.name==='department_id');
    if (hasDepartment && departmentField) await loadReferences([departmentField]);
    if(!activeLoad(loadId))return;
    const readonly=isReadonly(key);
    const fields=meta.fields || [];
    const statusField=fields.find(field=>field.name==='status');
    const page=$('#page-content');
    const actions='<button class="button secondary" id="export-records">'+icon('download')+'导出 CSV</button>'+(key==='payroll'?(meta.can_write===false?'':'<button class="button secondary" id="pay-all">'+icon('wallet')+'发放本月工资</button><button class="button primary" id="generate-payroll">'+icon('plus')+'生成月度工资</button>'):readonly?'':'<button class="button primary" id="new-record">'+icon('plus')+'新增'+esc(meta.title.replace(/管理|记录|信息|档案/g,''))+'</button>');
    const special=key==='payroll'?'<div class="resource-intro">'+icon('info')+'<span>工资按所选月份汇总：基本工资 + 加班 + 计件 + 计时 + 奖励 − 处罚 − 水电 − 个人社保 − 无薪假扣款。已发放工资将锁定，重新生成只更新未发放记录。</span></div>':key==='users'?'<div class="resource-intro">'+icon('shield')+'<span>为账户分配角色后，用户只能访问该角色被授权的模块。密码至少 8 位；修改权限后请重新登录以刷新导航。</span></div>':'';
    page.innerHTML=setPageHeading(state.route.startsWith('query/')?'员工公共查询':meta.title,resourceDescription(key),actions,'PEOPLE OPERATIONS')+special+'<section class="panel">'+(key==='payroll'?'<div id="payroll-summary"></div>':'')+'<form class="filters" id="filter-form"><div class="search-input">'+icon('search')+'<input name="q" aria-label="搜索记录" value="'+esc(filters.q || '')+'" placeholder="'+esc(key==='employees'?'搜索姓名、工号、手机号…':'搜索'+meta.title+'…')+'"></div>'+(key==='payroll'?'<label class="filter-label" for="payroll-month">核算月份</label><input id="payroll-month" type="month" name="month" required value="'+esc(filters.month)+'">':'')+(hasDepartment&&departmentField?'<select name="department" aria-label="部门筛选"><option value="">全部部门</option>'+referenceOptions(departmentField).map(option=>'<option value="'+esc(option.value)+'" '+(String(filters.department)===String(option.value)?'selected':'')+'>'+esc(option.label)+'</option>').join('')+'</select>':'')+(statusField?.options?'<select name="status" aria-label="状态筛选"><option value="">全部状态</option>'+optionList(statusField.options).map(option=>'<option value="'+esc(option.value)+'" '+(String(filters.status)===String(option.value)?'selected':'')+'>'+esc(option.label)+'</option>').join('')+'</select>':'')+'<button class="button secondary" type="submit">查询</button><button class="button ghost" type="button" id="reset-filters">重置</button><span class="filter-spacer"></span><span class="count-label">共 '+esc(data.total ?? state.records.length)+' 条记录</span></form><div id="records-table"></div></section>'+pageFooter();
    renderTable(key);
    $('#filter-form').addEventListener('submit',event=>{event.preventDefault();state.filters=Object.fromEntries(new FormData(event.target));state.page=1;loadRoute();});
    $('#reset-filters').addEventListener('click',()=>{state.filters=key==='payroll'?{month:filters.month}:{};state.page=1;loadRoute();});
    $('#export-records').addEventListener('click',()=>downloadCSV(key,state.filters));
    $('#new-record')?.addEventListener('click',()=>openRecordForm(key));
    if(key==='payroll') {
      $('#generate-payroll')?.addEventListener('click',()=>generatePayroll());
      $('#pay-all')?.addEventListener('click',()=>payPayroll());
      $('#payroll-month').addEventListener('change',()=>$('#filter-form').requestSubmit());
      renderPayrollSummary();
    }
  }
  function renderTable(key) {
    const meta=resourceMeta(key);const fields=meta.fields || [];
    const columns=(meta.columns || fields.filter(field=>field.type!=='password').map(field=>field.name)).map(column=>typeof column==='object'?column:(fields.find(field=>field.name===column)||{name:column,label:fields.find(field=>field.name===column.replace(/_name$/,'_id'))?.label || {employee_name:'员工',department_name:'部门',created_at:'创建时间',updated_at:'更新时间',id:'编号'}[column]||column}));
    const count=state.records.length;const pages=Math.max(1,Math.ceil(count/state.pageSize));state.page=Math.min(state.page,pages);
    const start=(state.page-1)*state.pageSize;
    const visible=state.records.slice(start,start+state.pageSize);
    const readonly=isReadonly(key);const payroll=key==='payroll'&&meta.can_write!==false;
    const container=$('#records-table');
    if(!count){container.innerHTML=emptyState('没有找到记录',Object.values(state.filters).some(Boolean)?'试试调整搜索条件，或清除筛选后重新查询。':'开始添加记录，建立团队的管理档案。',!readonly?'<button class="button secondary" id="empty-add">'+icon('plus')+'新增记录</button>':'');$('#empty-add')?.addEventListener('click',()=>openRecordForm(key));return;}
    container.innerHTML='<div class="table-scroll"><table class="record-table"><thead><tr>'+(payroll?'<th style="width:45px"><input type="checkbox" id="select-all" aria-label="全选当前页未发放工资"></th>':'')+columns.map(field=>'<th>'+esc(field.label || field.name)+'</th>').join('')+'<th>操作</th></tr></thead><tbody>'+visible.map(record=>'<tr>'+(payroll?'<td><input type="checkbox" data-select="'+esc(record.id)+'" aria-label="选择 '+esc(record.employee_name || '员工')+' 的工资" '+(isPaid(record)?'disabled':'')+' '+(state.selected.has(record.id)?'checked':'')+'></td>':'')+columns.map(field=>'<td class="'+(field.type==='textarea'?'cell-truncate':'')+'">'+tableCell(record,field,key)+'</td>').join('')+'<td><div class="row-actions"><button class="icon-button" data-view="'+esc(record.id)+'" title="查看详情" aria-label="查看记录详情">'+icon('eye')+'</button>'+(key==='notices'?'<button class="icon-button" data-print="'+esc(record.id)+'" title="打印通知" aria-label="打印通知">'+icon('print')+'</button>':'')+(payroll?(!isPaid(record)?'<button class="button secondary small" data-pay="'+esc(record.id)+'">发放</button>':'<span class="muted" style="font-size:10px">已锁定</span>'):!readonly?'<button class="icon-button" data-edit="'+esc(record.id)+'" title="编辑" aria-label="编辑记录">'+icon('edit')+'</button><button class="icon-button danger-text" data-delete="'+esc(record.id)+'" title="删除" aria-label="删除记录">'+icon('trash')+'</button>':'')+'</div></td></tr>').join('')+'</tbody></table></div><div class="table-bottom"><span>显示 '+(start+1)+'–'+Math.min(start+state.pageSize,count)+' 条，共 '+count+' 条</span>'+(payroll?'<button class="text-button table-selection" id="pay-selected" '+(!state.selected.size?'disabled':'')+'>发放所选 <span id="selection-count">'+state.selected.size+'</span> 条</button>':'')+'<div class="pagination"><label for="page-size">每页</label><select id="page-size">'+[10,15,30,50].map(size=>'<option '+(size===state.pageSize?'selected':'')+'>'+size+'</option>').join('')+'</select><button class="button secondary" id="prev-page" '+(state.page===1?'disabled':'')+' aria-label="上一页">‹</button><span>'+state.page+' / '+pages+'</span><button class="button secondary" id="next-page" '+(state.page===pages?'disabled':'')+' aria-label="下一页">›</button></div></div>';
    $$('[data-view]',container).forEach(button=>button.addEventListener('click',()=>openRecordDetail(key,state.records.find(record=>String(record.id)===button.dataset.view))));
    $$('[data-edit]',container).forEach(button=>button.addEventListener('click',()=>openRecordForm(key,state.records.find(record=>String(record.id)===button.dataset.edit))));
    $$('[data-delete]',container).forEach(button=>button.addEventListener('click',()=>deleteRecord(key,state.records.find(record=>String(record.id)===button.dataset.delete))));
    $$('[data-print]',container).forEach(button=>button.addEventListener('click',()=>printNotice(state.records.find(record=>String(record.id)===button.dataset.print))));
    $('#prev-page')?.addEventListener('click',()=>{state.page--;renderTable(key);});
    $('#next-page')?.addEventListener('click',()=>{state.page++;renderTable(key);});
    $('#page-size')?.addEventListener('change',event=>{state.pageSize=Number(event.target.value);state.page=1;renderTable(key);});
    if(payroll){
      $$('[data-select]',container).forEach(input=>input.addEventListener('change',()=>{const id=Number(input.dataset.select);input.checked?state.selected.add(id):state.selected.delete(id);updateSelection();}));
      $('#select-all').addEventListener('change',event=>{$$('[data-select]:not(:disabled)',container).forEach(input=>{input.checked=event.target.checked;const id=Number(input.dataset.select);input.checked?state.selected.add(id):state.selected.delete(id);});updateSelection();});
      $$('[data-pay]',container).forEach(button=>button.addEventListener('click',()=>payPayroll([Number(button.dataset.pay)])));
      $('#pay-selected').addEventListener('click',()=>payPayroll([...state.selected]));
      updateSelection();
    }
  }
  function tableCell(record,field,key) {
    let value=displayValue(record,field);
    if(isMultiple(field)){
      const options=optionList(field.options || state.meta.permissions || []);
      let values=record[field.name];
      if(typeof values==='string')try{values=JSON.parse(values);}catch(_){values=values.split(',');}
      if(Array.isArray(values))value=values.map(v=>options.find(o=>String(o.value)===String(v))?.label||({all:'全部模块'}[v])||v).join('、') || '无';
    }
    if(['status','approval_status','payment_status','result'].includes(field.name))return statusBadge(value);
    if(field.type==='money'||/salary|amount|_pay$|_wage$|deduction|base_salary|net_salary|net_pay|gross|cost|fee$|bonus|penalty|insurance/.test(field.name)&&!field.reference&&Number.isFinite(Number(record[field.name]))&&record[field.name]!==null)return '<span class="money">'+currency(record[field.name])+'</span>';
    if(field.type==='password')return '••••••••';
    if(field.type==='date')value=shortDate(value==='—'?'':value);
    if(field.name==='name'&&key==='employees')return '<div class="employee-cell"><div class="avatar">'+esc(value.slice(0,1))+'</div><span>'+esc(value)+'</span></div>';
    return '<span title="'+esc(value)+'">'+esc(value.length>70?value.slice(0,70)+'…':value)+'</span>';
  }
  function updateSelection() {
    $('#selection-count').textContent=state.selected.size;$('#pay-selected').disabled=!state.selected.size;
    const selectable=$$('[data-select]:not(:disabled)');const checked=selectable.filter(input=>input.checked);
    $('#select-all').checked=!!selectable.length&&checked.length===selectable.length;$('#select-all').indeterminate=checked.length>0&&checked.length<selectable.length;
  }
  function isPaid(record) { return !!record.paid_at || ['paid','已发放','已支付'].includes(record.status) || ['paid','已发放','已支付'].includes(record.payment_status); }
  function payrollNet(record) { return Number(record.net_salary ?? record.net_pay ?? record.actual_salary ?? record.total ?? 0); }
  function renderPayrollSummary() {
    const unpaid=state.records.filter(record=>!isPaid(record));const paid=state.records.length-unpaid.length;
    $('#payroll-summary').innerHTML='<div class="payroll-summary"><span>实发合计<strong>¥ '+currency(state.records.reduce((sum,record)=>sum+payrollNet(record),0))+'</strong></span><span>待发放<strong>'+unpaid.length+'</strong> 人</span><span>已发放<strong>'+paid+'</strong> 人</span><span class="badge">'+esc(state.filters.month)+' 月度工资</span></div>';
    if($('#pay-all'))$('#pay-all').disabled=!unpaid.length;
  }
  async function generatePayroll() {
    const month=$('#payroll-month').value;
    if(!month){toast('请先选择核算月份。',true);return;}
    if(!await confirmAction('生成 '+month+' 月工资','系统将汇总在职员工的收入、扣款和社保。已有的未发放记录将重新计算，已发放记录保持锁定。','确认生成'))return;
    const button=$('#generate-payroll');button.disabled=true;button.innerHTML='<span class="spinner"></span>核算中…';
    try{const result=await api('/payroll/generate',{method:'POST',body:{month}});toast('月度工资生成完成，共 '+(result.count ?? result.items?.length ?? 0)+' 条。');state.filters={...state.filters,month};await loadRoute();}
    catch(error){toast(error.message,true);button.disabled=false;button.innerHTML=icon('plus')+'生成月度工资';}
  }
  async function payPayroll(ids) {
    if(ids && !ids.length)return;
    const month=state.filters.month;
    let selected;
    try { selected=ids?state.records.filter(record=>ids.includes(record.id)):(await api('/records/payroll'+makeQuery({month}))).items.filter(record=>!isPaid(record)); }
    catch(error){toast(error.message,true);return;}
    const amount=selected.reduce((sum,record)=>sum+payrollNet(record),0);
    if(!selected.length){toast('没有待发放的工资。');return;}
    if(!await confirmAction('确认工资发放','将发放 '+month+' 月 '+selected.length+' 位员工的工资，合计 ¥ '+currency(amount)+'。发放后记录将锁定，请先核对明细。','确认发放'))return;
    try{const body={month};if(ids)body.ids=ids;const result=await api('/payroll/pay',{method:'POST',body});toast('已发放 '+result.count+' 条工资。');await loadRoute();}
    catch(error){toast(error.message,true);}
  }

  async function openRecordForm(key, record = null) {
    const meta=resourceMeta(key);if(!meta)return;
    $('#dialog-content').innerHTML='<div class="modal-heading"><h2>'+esc(record?'编辑'+meta.title:'新增'+meta.title)+'</h2><button class="icon-button" data-close-dialog aria-label="关闭">'+icon('close')+'</button></div>'+loading();
    if(!recordDialog.open)recordDialog.showModal();
    $('[data-close-dialog]',recordDialog).addEventListener('click',()=>recordDialog.close());
    const missing=await loadReferences(meta.fields || []);
    if(!recordDialog.open)return;
    const fields=(meta.fields || []).filter(field=>!field.readonly&&field.name!=='id');
    const formHTML=fields.map(field=>formField(field,record)).join('');
    $('#dialog-content').innerHTML='<form id="record-form"><div class="modal-heading"><h2>'+esc(record?'编辑'+meta.title:'新增'+meta.title)+'</h2><button class="icon-button" type="button" data-close-dialog aria-label="关闭">'+icon('close')+'</button></div><div class="modal-body"><div id="form-error">'+(missing.length?errorBox('部分关联数据无法加载（'+missing.join('、')+'）。请确认账户权限，或先创建关联记录。'):'')+'</div><div class="form-grid">'+formHTML+'</div></div><div class="modal-footer"><span class="modal-save-note">标有 * 的项目为必填</span><button class="button secondary" type="button" data-close-dialog>取消</button><button class="button primary" type="submit" id="save-record">'+icon('check')+'保存记录</button></div></form>';
    $$('[data-close-dialog]',recordDialog).forEach(button=>button.addEventListener('click',()=>recordDialog.close()));
    $('#record-form').addEventListener('submit',async event=>{
      event.preventDefault();const button=$('#save-record');button.disabled=true;button.innerHTML='<span class="spinner"></span>保存中…';$('#form-error').innerHTML='';
      try{
        const data=collectForm(event.target,fields,!!record);
        await api('/records/'+encodeURIComponent(key)+(record?'/'+record.id:''),{method:record?'PUT':'POST',body:data});
        state.refs={};recordDialog.close();toast(record?'记录已更新。':'记录已创建。');
        if (['menus','dictionaries','roles','users'].includes(key)) {
          const session=await api('/session');state.user=session.user;state.csrf=session.csrf;
          state.meta=await api('/meta');renderNav();
        }
        await loadRoute();
      }catch(error){if(!state.user)return;if(!recordDialog.open){toast(error.message,true);return;}$('#form-error').innerHTML=errorBox(error.message);$('.modal-body',recordDialog).scrollTop=0;button.disabled=false;button.innerHTML=icon('check')+'保存记录';}
    });
    $('input:not([type=checkbox]),select,textarea',recordDialog)?.focus();
  }
  function formField(field,record) {
    const id='field-'+field.name;
    let value=record ? record[field.name] : field.default ?? '';
    if(value==null)value='';
    const editing=!!record;
    const required=(field.required||field.type==='password'&&!editing)&&!(editing&&field.type==='password');
    const label='<label for="'+esc(id)+'">'+esc(field.label || field.name)+(required?'<span class="required">*</span>':'')+'</label>';
    let input='';
    let hint='';
    if(isMultiple(field)){
      let values=Array.isArray(value)?value:[];
      if(typeof value==='string'&&value)try{values=JSON.parse(value);}catch(_){values=value.split(',');}
      const options=optionList(field.options || (state.meta.permissions || []).map(item=>({value:item.id,label:item.title})));
      input='<div class="permissions-grid" id="'+esc(id)+'" role="group" aria-label="'+esc(field.label)+'">'+options.map(option=>'<label><input name="'+esc(field.name)+'" type="checkbox" value="'+esc(option.value)+'" '+(values.includes(String(option.value))||values.includes(option.value)?'checked':'')+'>'+esc(option.label)+'</label>').join('')+'</div>';
      hint='勾选允许访问的模块；未勾选的模块将不可访问。';
    }else if(field.reference || field.options){
      const options=field.reference?referenceOptions(field):optionList(field.options);
      const existing=options.some(option=>String(option.value)===String(value));
      input='<select name="'+esc(field.name)+'" id="'+esc(id)+'" '+(required?'required':'')+'><option value="">请选择'+esc(field.label || '')+'</option>'+(!existing&&value!==''?'<option selected value="'+esc(value)+'">'+esc(record?.[field.name.replace(/_id$/,'')+'_name'] || '当前值 #'+value)+'</option>':'')+options.map(option=>'<option value="'+esc(option.value)+'" '+(String(option.value)===String(value)?'selected':'')+'>'+esc(option.label)+'</option>').join('')+'</select>';
      if(field.reference&&!options.length)hint='暂无可选项，请先在相应模块中添加关联记录。';
    }else if(field.type==='textarea'){
      input='<textarea name="'+esc(field.name)+'" id="'+esc(id)+'" '+(required?'required':'')+' placeholder="请输入'+esc(field.label || '')+'">'+esc(value)+'</textarea>';
    }else if(field.type==='boolean'||field.type==='checkbox'){
      return '<div class="field checkbox-field"><input name="'+esc(field.name)+'" id="'+esc(id)+'" type="checkbox" '+(value?'checked':'')+'>'+label+'</div>';
    }else{
      const numeric=['integer','number','money','decimal'].includes(field.type);
      const type=numeric?'number':(['date','month','email','tel','password'].includes(field.type)?field.type:'text');
      const step=field.type==='integer'?'1':numeric?'any':null;
      input='<input name="'+esc(field.name)+'" id="'+esc(id)+'" type="'+type+'" '+(field.type==='password'?'autocomplete="new-password" minlength="8"':'')+' '+(step?'step="'+step+'"':'')+' '+(field.minimum!=null?'min="'+esc(field.minimum)+'"':'')+' '+(field.maximum!=null?'max="'+esc(field.maximum)+'"':'')+' '+(required?'required':'')+' value="'+esc(field.type==='password'?'':value)+'" placeholder="'+esc(field.type==='password'&&editing?'留空则保留当前密码':'请输入'+(field.label || ''))+'">';
      if(field.type==='password'&&editing)hint='填写新密码将重设该用户密码；留空保留原密码。';
      if(/rate|ratio/.test(field.name))hint='比例按小数填写，例如 0.08 表示 8%。';
    }
    return '<div class="field '+(field.type==='textarea'||isMultiple(field)?'wide':'')+'">'+label+input+(hint?'<small>'+esc(hint)+'</small>':'')+'</div>';
  }
  function openRecordDetail(key,record) {
    if(key==='notices'){openNotice(record);return;}
    const meta=resourceMeta(key);
    const fields=(meta.fields || []).filter(field=>field.type!=='password');
    $('#dialog-content').innerHTML='<div class="modal-heading"><h2>'+esc(meta.title)+'详情</h2><button class="icon-button" data-close-dialog aria-label="关闭">'+icon('close')+'</button></div><div class="modal-body"><div class="view-detail">'+fields.map(field=>'<div class="detail-item '+(field.type==='textarea'||isMultiple(field)?'wide':'')+'"><label>'+esc(field.label || field.name)+'</label><p>'+tableCell(record,field,key)+'</p></div>').join('')+'</div></div><div class="modal-footer"><span class="modal-save-note">记录编号 #'+esc(record.id)+'</span><button class="button secondary" data-close-dialog>关闭</button>'+(!isReadonly(key)?'<button class="button primary" id="edit-from-detail">'+icon('edit')+'编辑记录</button>':'')+'</div>';
    $$('[data-close-dialog]',recordDialog).forEach(button=>button.addEventListener('click',()=>recordDialog.close()));
    $('#edit-from-detail')?.addEventListener('click',()=>openRecordForm(key,record));
    if(!recordDialog.open)recordDialog.showModal();
  }
  async function deleteRecord(key,record) {
    const label=record.name || record.title || record.employee_name || '编号 #'+record.id;
    if(!await confirmAction('删除这条记录？','将删除“'+label+'”。删除后无法撤销；有关联业务时系统会阻止删除。','确认删除',true))return;
    try{await api('/records/'+encodeURIComponent(key)+'/'+record.id,{method:'DELETE'});state.refs={};toast('记录已删除。');if(['menus','dictionaries','roles','users'].includes(key)){const session=await api('/session');state.user=session.user;state.csrf=session.csrf;state.meta=await api('/meta');renderNav();}await loadRoute();}
    catch(error){toast(error.message,true);}
  }
  function confirmAction(title,description,accept='确认',danger=false) {
    $('#confirm-title').textContent=title;$('#confirm-description').textContent=description;
    $('#confirm-accept').textContent=accept;$('#confirm-accept').className='button '+(danger?'danger':'primary');$('#confirm-icon').innerHTML=icon(danger?'trash':'info');
    confirmDialog.returnValue='';confirmDialog.showModal();
    return new Promise(resolve=>confirmDialog.addEventListener('close',()=>resolve(confirmDialog.returnValue==='confirm'),{once:true}));
  }
  async function downloadCSV(key,filters={}) {
    try{
      const response=await fetch('/api/export/'+encodeURIComponent(key)+makeQuery(filters),{credentials:'same-origin'});
      if(!response.ok){let result;try{result=await response.json();}catch(_){}throw new Error(result?.error || '导出失败，请重试。');}
      const blob=await response.blob();const url=URL.createObjectURL(blob);const anchor=document.createElement('a');anchor.href=url;anchor.download=(resourceMeta(key)?.title || key)+'-'+localISO()+'.csv';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('CSV 已导出，可使用 Excel 打开。');
    }catch(error){toast(error.message,true);}
  }
  function exportLocalCSV(filename, rows) {
    const csv='\uFEFF'+rows.map(row=>row.map(csvCell).join(',')).join('\r\n');
    const blob=new Blob([csv],{type:'text/csv;charset=utf-8'});const url=URL.createObjectURL(blob);const anchor=document.createElement('a');anchor.href=url;anchor.download=filename;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('CSV 已导出。');
  }
  function noticeHTML(notice) {
    return '<h1>'+esc(notice.title || notice.name || '公司通知')+'</h1><p class="notice-meta">'+esc(notice.publisher || notice.author || '人事行政')+' · '+esc(shortDate(notice.publish_date || notice.date || notice.created_at))+'</p><div class="notice-content">'+esc(notice.content || notice.body || '暂无内容')+'</div>';
  }
  function openNotice(notice) {
    if(!notice)return;
    $('#dialog-content').innerHTML='<div class="modal-heading"><h2>公司通知</h2><button class="icon-button" data-close-dialog aria-label="关闭">'+icon('close')+'</button></div><div class="modal-body notice-print">'+noticeHTML(notice)+'</div><div class="modal-footer"><button class="button secondary" data-close-dialog>关闭</button><button class="button primary" id="print-notice">'+icon('print')+'打印通知</button></div>';
    $$('[data-close-dialog]',recordDialog).forEach(button=>button.addEventListener('click',()=>recordDialog.close()));$('#print-notice').addEventListener('click',()=>printNotice(notice));if(!recordDialog.open)recordDialog.showModal();
  }
  function printNotice(notice) {
    $('.print-target')?.remove();const target=document.createElement('article');target.className='print-target';target.innerHTML=noticeHTML(notice);document.body.append(target);
    window.print();
  }

  async function renderBirthdays(loadId) {
    const days=state.filters.days || '30';const data=await api('/birthdays'+makeQuery({days}));if(!activeLoad(loadId))return;
    setBreadcrumb('人事管理','员工生日');const items=data.items || [];
    $('#page-content').innerHTML=setPageHeading('员工生日','记得每一个特别的日子，给团队多一份关怀。','<button class="button secondary" id="export-birthdays">'+icon('download')+'导出名单</button>','A LITTLE CELEBRATION')+'<section class="panel"><form class="filters" id="birthday-filter"><label class="filter-label" for="birthday-days">查询未来</label><select id="birthday-days" name="days">'+[7,30,60,90,180,365].map(option=>'<option value="'+option+'" '+(String(days)===String(option)?'selected':'')+'>'+option+' 天</option>').join('')+'</select><button class="button secondary" type="submit">查询生日</button><span class="filter-spacer"></span><span class="count-label">共 '+items.length+' 位同事</span></form>'+(items.length?'<div class="table-scroll"><table><thead><tr><th>员工姓名</th><th>工号</th><th>部门</th><th>生日</th><th>即将到来的生日</th><th>年龄</th><th>还有</th></tr></thead><tbody>'+items.map(employee=>'<tr><td><div class="employee-cell"><div class="avatar">'+esc((employee.name||'员').slice(0,1))+'</div>'+esc(employee.name)+'</div></td><td>'+esc(employee.employee_no || '—')+'</td><td>'+esc(employee.department_name || '—')+'</td><td>'+esc(shortDate(employee.birthday || employee.birth_date))+'</td><td>'+esc(shortDate(employee.next_birthday))+'</td><td>'+esc(employee.age)+' 岁</td><td>'+statusBadge(Number(employee.days_until)===0?'今天生日':employee.days_until+' 天')+'</td></tr>').join('')+'</tbody></table></div>':emptyState('近期没有员工生日','调整查询范围，查看更长时间内的生日。'))+'</section>'+pageFooter();
    $('#birthday-filter').addEventListener('submit',event=>{event.preventDefault();state.filters.days=$('#birthday-days').value;loadRoute();});
    $('#export-birthdays').addEventListener('click',()=>exportLocalCSV('员工生日-'+localISO()+'.csv',[['姓名','工号','部门','生日','下次生日','年龄','剩余天数'],...items.map(item=>[item.name,item.employee_no,item.department_name,item.birthday || item.birth_date,item.next_birthday,item.age,item.days_until])]));
  }
  function horizontalChart(items) {
    if(!items?.length)return emptyState('暂无统计数据','记录员工信息后即可查看统计。');
    const max=Math.max(...items.map(item=>Number(item.value || 0)),1);
    return '<div class="horizontal-bars">'+items.map((item,i)=>'<div class="horizontal-bar"><span>'+esc(item.label)+'</span><div class="horizontal-track"><div class="horizontal-fill" style="width:'+Math.min(Number(item.value||0)/max*100,100)+'%;background:'+colors[i%colors.length]+'"></div></div><strong>'+esc(item.value)+' 人</strong></div>').join('')+'</div>';
  }
  function monthlyChart(items,kind='both') {
    if(!items?.length)return emptyState('暂无月度数据','选择有员工入职或离职记录的年份。');
    const max=Math.max(...items.flatMap(item=>kind==='both'?[Number(item.joined||0),Number(item.resigned||0)]:[Number(item[kind]||0)]),1);
    return '<div class="chart-bars">'+items.map(item=>'<div class="chart-column"><div class="bar-pair">'+(kind!=='resigned'?'<div class="bar" style="height:'+Number(item.joined||0)/max*100+'%" title="'+esc(item.month)+'月入职 '+Number(item.joined||0)+' 人"></div>':'')+(kind!=='joined'?'<div class="bar alt" style="height:'+Number(item.resigned||0)/max*100+'%" title="'+esc(item.month)+'月离职 '+Number(item.resigned||0)+' 人"></div>':'')+'</div><small>'+esc(String(item.month).slice(-2).replace(/^0/,''))+'月</small></div>').join('')+'</div><div class="chart-key">'+(kind!=='resigned'?'<span><i></i>入职人数</span>':'')+(kind!=='joined'?'<span><i class="alt"></i>离职人数</span>':'')+'</div>';
  }
  async function renderReports(loadId) {
    const year=state.filters.year || new Date().getFullYear();const data=await api('/reports'+makeQuery({year}));if(!activeLoad(loadId))return;
    setBreadcrumb('统计报表','人事统计报表');const summary=data.summary || {};
    const charts=[{title:'员工性别统计',data:data.gender,note:'按员工档案中的性别统计'}, {title:'学历结构统计',data:data.education,note:'按员工最高学历统计'}, {title:'工龄结构统计',data:data.tenure,note:'以入职日期计算员工工龄'}, {title:'年龄结构统计',data:data.age,note:'以出生日期计算员工年龄'}, {title:'部门人员统计',data:data.departments,note:'按部门统计在职员工数量'}];
    const page=$('#page-content');
    page.innerHTML=setPageHeading('人事统计报表','从数据看见团队结构，支持每一次管理决策。','<label class="filter-label" for="report-year">统计年度</label><input id="report-year" type="number" min="1900" max="2200" step="1" value="'+esc(year)+'" style="width:100px"><button class="button secondary" id="apply-report-year">查询</button><button class="button secondary" id="export-reports">'+icon('download')+'导出报表</button>','WORKFORCE INSIGHTS')+'<div class="metrics-grid">'+[{label:'员工档案总数',value:summary.total,unit:'人',symbol:'people'}, {label:'目前在职',value:summary.active,unit:'人',symbol:'building'}, {label:'本年度离职',value:summary.resigned,unit:'人',symbol:'logout'}, {label:'年度离职率',value:Number(summary.turnover_rate || 0).toFixed(2),unit:'%',symbol:'chart'}].map(item=>'<div class="metric-card"><div class="metric-header"><span>'+item.label+'</span><div class="metric-icon">'+icon(item.symbol)+'</div></div><div class="metric-value">'+esc(item.value ?? '—')+'<span class="metric-unit">'+item.unit+'</span></div><div class="metric-note">'+esc(year)+' 年度统计</div></div>').join('')+'</div><div class="stats-grid">'+charts.map(chart=>'<section class="panel"><div class="panel-head"><h2>'+chart.title+'</h2><span class="badge">'+esc(year)+'</span></div><div class="panel-body">'+horizontalChart(chart.data)+'<p class="report-note">'+chart.note+'</p></div></section>').join('')+'<section class="panel"><div class="panel-head"><h2>员工离职率</h2><span class="badge amber">年度指标</span></div><div class="panel-body"><div class="turnover-display"><strong>'+Number(summary.turnover_rate || 0).toFixed(2)+'%</strong><div>统计年度：'+esc(year)+'<br>当前在职：'+esc(summary.active || 0)+' 人<br>本年度离职：'+esc(summary.resigned || 0)+' 人</div></div><p class="report-note">离职率根据服务端统一统计口径计算。离职日期在员工档案中维护。</p></div></section><section class="panel"><div class="panel-head"><h2>月度入职统计</h2><span class="muted" style="font-size:11px">'+esc(year)+' 年</span></div><div class="panel-body">'+monthlyChart(data.monthly,'joined')+'</div></section><section class="panel"><div class="panel-head"><h2>月度离职统计</h2><span class="muted" style="font-size:11px">'+esc(year)+' 年</span></div><div class="panel-body">'+monthlyChart(data.monthly,'resigned')+'</div></section><section class="panel" style="grid-column:1/-1"><div class="panel-head"><h2>月度人员变动明细</h2><span class="muted" style="font-size:11px">图表对应明细</span></div><div class="table-scroll"><table class="report-monthly"><thead><tr><th>月份</th><th>入职人数</th><th>离职人数</th><th>净增人数</th></tr></thead><tbody>'+(data.monthly || []).map(item=>'<tr><td>'+esc(item.month)+' 月</td><td>'+esc(item.joined)+' 人</td><td>'+esc(item.resigned)+' 人</td><td>'+esc(Number(item.joined)-Number(item.resigned))+' 人</td></tr>').join('')+'</tbody></table></div></section></div>'+pageFooter();
    $('#apply-report-year').addEventListener('click',()=>{const input=$('#report-year');if(!input.reportValidity())return;state.filters.year=input.value;loadRoute();});
    $('#export-reports').addEventListener('click',()=>{
      const rows=[['报表','分类','人数 / 指标'], ['总览','员工档案总数',summary.total],['总览','在职人数',summary.active],['总览','离职人数',summary.resigned],['离职率','百分比',summary.turnover_rate]];
      charts.forEach(chart=>(chart.data || []).forEach(item=>rows.push([chart.title,item.label,item.value])));
      (data.monthly || []).forEach(item=>{rows.push(['月度入职',item.month,item.joined]);rows.push(['月度离职',item.month,item.resigned]);});
      exportLocalCSV('人事统计报表-'+year+'.csv',rows);
    });
  }
  async function renderAudit(loadId) {
    const data=await api('/audit');if(!activeLoad(loadId))return;
    setBreadcrumb('系统设置','操作日志');const records=data.items || [];
    const fields=[{name:'created_at',label:'操作时间'}, {name:'username',label:'操作用户'}, {name:'action',label:'操作'}, {name:'resource',label:'业务'}, {name:'record_id',label:'记录编号'}, {name:'detail',label:'说明'}];
    $('#page-content').innerHTML=setPageHeading('操作日志','查看系统中的关键数据修改与管理操作。','<button class="button secondary" id="export-audit">'+icon('download')+'导出日志</button>','SYSTEM ACTIVITY')+'<section class="panel"><div class="filters"><div class="search-input">'+icon('search')+'<input id="audit-search" placeholder="搜索用户、业务或操作…" aria-label="搜索日志"></div><span class="filter-spacer"></span><span class="count-label">最近 '+records.length+' 条记录</span></div><div id="audit-table"></div></section>'+pageFooter();
    function show(items){$('#audit-table').innerHTML=items.length?'<div class="table-scroll"><table><thead><tr>'+fields.map(field=>'<th>'+field.label+'</th>').join('')+'</tr></thead><tbody>'+items.map(record=>'<tr>'+fields.map(field=>'<td>'+esc(field.name==='resource'?(resourceMeta(record.resource)?.title || record.resource || '—'):(record[field.name] ?? (field.name==='username'?record.user_name:field.name==='detail'?record.details:undefined) ?? '—'))+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>':emptyState('暂无操作日志','后续数据变更将在这里记录。');}
    show(records);$('#audit-search').addEventListener('input',event=>{const q=event.target.value.trim().toLowerCase();show(records.filter(record=>JSON.stringify(record).toLowerCase().includes(q)));});
    $('#export-audit').addEventListener('click',()=>exportLocalCSV('操作日志-'+localISO()+'.csv',[fields.map(field=>field.label),...records.map(record=>fields.map(field=>record[field.name]))]));
  }

  window.addEventListener('hashchange',loadRoute);
  recordDialog.addEventListener('click',event=>{if(event.target===recordDialog){const rect=recordDialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)recordDialog.close();}});
  async function init() {
    try{const session=await api('/session');await startSession(session);}
    catch(error){showLogin(error.status===401?'':error.message);}
  }
  init();
})();
