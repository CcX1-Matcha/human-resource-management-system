"""Local HTTP entry point for the human resource management application."""

import argparse
import json
import logging
import mimetypes
import secrets
import threading
import time
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from hrm.service import HRMError, HRMService

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / 'static'
MAX_BODY = 1024 * 1024
SESSION_TTL = 8 * 60 * 60
LOG = logging.getLogger('hrm')


class HRMServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service):
        self.service = service
        self.sessions = {}
        self.login_attempts = {}
        self.lock = threading.RLock()
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = 'HRM/1.0'

    def log_message(self, format, *args):
        LOG.info('%s %s', self.client_address[0], format % args)

    def _reply(self, status, body, content_type='application/json; charset=utf-8', headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _body(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise HRMError('请求长度无效', 400)
        if length < 0 or length > MAX_BODY:
            raise HRMError('请求内容过大', 413)
        if not length:
            return {}
        if self.headers.get_content_type() != 'application/json':
            raise HRMError('请使用 JSON 请求格式', 415)
        try:
            def reject_constant(value):
                raise ValueError('Invalid JSON number: ' + value)
            data = json.loads(self.rfile.read(length).decode('utf-8'), parse_constant=reject_constant)
        except (ValueError, UnicodeError, RecursionError):
            raise HRMError('请求内容不是有效的 JSON', 400)
        if not isinstance(data, dict):
            raise HRMError('请求内容必须是对象', 400)
        return data

    def _token(self):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            return cookie['hrm_session'].value if 'hrm_session' in cookie else ''
        except Exception:
            return ''

    def _session(self):
        now = time.monotonic()
        with self.server.lock:
            token = self._token()
            session = self.server.sessions.get(token)
            if not session or session['expires'] <= now:
                self.server.sessions.pop(token, None)
                raise HRMError('请先登录，或重新登录已过期的会话', 401)
            session = dict(session)
        user = self.server.service.user(session['user_id'])
        if not user or user.get('status') in ('禁用', '停用', 'disabled'):
            raise HRMError('账号已停用，请联系管理员', 401)
        return user, session

    def _origin(self):
        origin = self.headers.get('Origin')
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme != 'http' or parsed.netloc.lower() != self.headers.get('Host', '').lower():
                raise HRMError('不允许来自其他网站的操作请求', 403)
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise HRMError('不允许跨站操作', 403)

    def _csrf(self, session):
        self._origin()
        received = self.headers.get('X-CSRF-Token', '')
        if not received.isascii() or not secrets.compare_digest(received, session['csrf']):
            raise HRMError('操作验证失效，请刷新页面后重试', 403)

    def _login(self):
        self._origin()
        data = self._body()
        username = data.get('username', '')
        password = data.get('password', '')
        if not isinstance(username, str) or not isinstance(password, str):
            raise HRMError('用户名和密码格式无效', 400)
        if len(username) > 100 or len(password) > 1024:
            raise HRMError('用户名或密码过长', 400)
        username = username.strip()
        key = (self.client_address[0], username)
        now = time.monotonic()
        with self.server.lock:
            self.server.login_attempts = {k: v for k, v in self.server.login_attempts.items() if v['until'] > now}
            attempts = self.server.login_attempts.get(key, {'count': 0, 'until': now + 60})
            if attempts['count'] >= 10:
                raise HRMError('登录尝试过多，请一分钟后重试', 429)
            attempts['count'] += 1
            self.server.login_attempts[key] = attempts
        user = self.server.service.login(username, password)
        if not user:
            raise HRMError('用户名或密码错误', 401)
        csrf = secrets.token_urlsafe(32)
        token = secrets.token_urlsafe(32)
        with self.server.lock:
            self.server.login_attempts.pop(key, None)
            self.server.sessions = {k: s for k, s in self.server.sessions.items() if s['expires'] > now}
            self.server.sessions.pop(self._token(), None)
            self.server.sessions[token] = {'user_id': user['id'], 'csrf': csrf, 'expires': now + SESSION_TTL}
        self._reply(200, {'user': user, 'csrf': csrf}, headers={'Set-Cookie': 'hrm_session=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=%s' % (token, SESSION_TTL)})

    def _static(self, path):
        relative = 'index.html' if path == '/' else (path[8:] if path.startswith('/static/') else path.lstrip('/'))
        candidate = (STATIC / relative).resolve()
        if not candidate.is_relative_to(STATIC.resolve()) or not candidate.is_file():
            raise HRMError('页面不存在', 404)
        content_type = mimetypes.guess_type(str(candidate))[0] or 'application/octet-stream'
        if content_type.startswith('text/') or content_type in ('application/javascript', 'application/json'):
            content_type += '; charset=utf-8'
        self._reply(200, candidate.read_bytes(), content_type)

    def _dispatch(self):
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        method = self.command
        if not path.startswith('/api/'):
            if method not in ('GET', 'HEAD'):
                raise HRMError('此页面不支持该操作', 405)
            return self._static(path)
        if path == '/api/login' and method == 'POST':
            return self._login()
        user, session = self._session()
        if method not in ('GET', 'HEAD'):
            self._csrf(session)
        service = self.server.service
        filters = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
        if path == '/api/session' and method == 'GET':
            return self._reply(200, {'user': user, 'csrf': session['csrf']})
        if path == '/api/logout' and method == 'POST':
            with self.server.lock:
                self.server.sessions.pop(self._token(), None)
            return self._reply(200, {'ok': True}, headers={'Set-Cookie': 'hrm_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'})
        if path == '/api/meta' and method == 'GET':
            return self._reply(200, service.meta(user))
        if path == '/api/dashboard' and method == 'GET':
            return self._reply(200, service.dashboard(user))
        if path == '/api/birthdays' and method == 'GET':
            return self._reply(200, service.birthdays(filters.get('days', '30'), user))
        if path == '/api/reports' and method == 'GET':
            return self._reply(200, service.reports(filters.get('year', time.strftime('%Y')), user))
        if path == '/api/audit' and method == 'GET':
            return self._reply(200, service.audit(user))
        if path == '/api/payroll/generate' and method == 'POST':
            return self._reply(200, service.generate_payroll(self._body().get('month'), user))
        if path == '/api/payroll/pay' and method == 'POST':
            data = self._body()
            return self._reply(200, service.pay_payroll(data.get('month'), data.get('ids'), user))
        segments = path.strip('/').split('/')
        if len(segments) == 3 and segments[:2] == ['api', 'export'] and method == 'GET':
            content = service.export_csv(segments[2], filters, user)
            if isinstance(content, str):
                content = content.encode('utf-8-sig')
            elif not content.startswith(b'\xef\xbb\xbf'):
                content = b'\xef\xbb\xbf' + content
            return self._reply(200, content, 'text/csv; charset=utf-8', {'Content-Disposition': 'attachment; filename="hrm-export.csv"'})
        if len(segments) in (3, 4) and segments[:2] == ['api', 'records']:
            resource = segments[2]
            if len(segments) == 3:
                if method == 'GET':
                    return self._reply(200, service.list_records(resource, filters, user))
                if method == 'POST':
                    return self._reply(201, service.create(resource, self._body(), user))
            else:
                try:
                    record_id = int(segments[3])
                except ValueError:
                    raise HRMError('记录编号无效', 400)
                if method == 'PUT':
                    return self._reply(200, service.update(resource, record_id, self._body(), user))
                if method == 'DELETE':
                    result = service.delete(resource, record_id, user)
                    return self._reply(200, result if result is not None else {'ok': True})
        raise HRMError('接口不存在或不支持该操作', 404)

    def _handle(self):
        self.connection.settimeout(15)
        try:
            self._dispatch()
        except HRMError as error:
            self._reply(getattr(error, 'status', 400), {'error': str(error)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            LOG.info('Client connection closed')
        except Exception:
            LOG.exception('Request failed: %s %s', self.command, self.path.split('?')[0])
            self._reply(500, {'error': '服务器处理失败，请查看运行窗口或联系管理员'})

    do_GET = _handle
    do_HEAD = _handle
    do_POST = _handle
    do_PUT = _handle
    do_DELETE = _handle


def create_server(host='127.0.0.1', port=8000, db_path=None, seed=True):
    return HRMServer((host, port), HRMService(db_path or ROOT / 'data' / 'hrm.db', seed=seed))


def main():
    parser = argparse.ArgumentParser(description='人力资源管理系统（本地版）')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--db', type=Path, default=ROOT / 'data' / 'hrm.db')
    parser.add_argument('--no-seed', action='store_true', help='新建数据库时不导入业务演示数据')
    parser.add_argument('--open', action='store_true', help='启动时打开浏览器')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    try:
        server = create_server(args.host, args.port, args.db, seed=not args.no_seed)
    except OSError as error:
        print('启动失败：%s。若端口被占用，可使用 --port 8001。' % error)
        return 1
    url = 'http://%s:%s' % ('127.0.0.1' if args.host == '0.0.0.0' else args.host, server.server_port)
    print('人力资源管理系统已启动：%s' % url)
    print('初始管理员：admin / Admin123!；演示账号仅用于本地课程实践。')
    print('数据文件：%s' % args.db.resolve())
    print('按 Ctrl+C 停止。')
    if args.open:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n正在停止服务……')
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
