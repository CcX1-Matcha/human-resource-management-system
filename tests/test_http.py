import http.cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app import create_server


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.server = create_server('127.0.0.1', 0, Path(cls.tmp.name) / 'test.db', seed=False)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:%s' % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.tmp.cleanup()

    def setUp(self):
        self.client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = None

    def request(self, path, method='GET', body=None, csrf=True, headers=None):
        hdr = dict(headers or {})
        if body is not None:
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
            hdr['Content-Type'] = 'application/json'
        if self.csrf and csrf:
            hdr['X-CSRF-Token'] = self.csrf
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=hdr)
        try:
            with self.client.open(req, timeout=10) as response:
                raw = response.read()
                data = json.loads(raw) if response.headers.get_content_type() == 'application/json' else raw
                return response.status, data, response.headers
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read()), error.headers

    def login(self):
        status, data, _ = self.request('/api/login', 'POST', {'username': 'admin', 'password': 'Admin123!'})
        self.assertEqual(200, status, data)
        self.csrf = data['csrf']
        return data

    def test_unauthenticated_requests_are_denied(self):
        status, data, _ = self.request('/api/records/employees')
        self.assertEqual(401, status)
        self.assertIn('error', data)

    def test_login_session_and_logout(self):
        login = self.login()
        self.assertEqual('admin', login['user']['username'])
        status, session, _ = self.request('/api/session')
        self.assertEqual(200, status)
        self.assertEqual(login['csrf'], session['csrf'])
        self.assertEqual(200, self.request('/api/logout', 'POST', {})[0])
        self.assertEqual(401, self.request('/api/session')[0])

    def test_csrf_blocks_writes(self):
        self.login()
        status, _, _ = self.request('/api/records/departments', 'POST', {'name': 'CSRF测试'}, csrf=False)
        self.assertEqual(403, status)

    def test_non_ascii_csrf_is_denied_without_server_error(self):
        self.login()
        status, _, _ = self.request('/api/records/departments', 'POST', {'name': '异常令牌'}, csrf=False, headers={'X-CSRF-Token': 'é'})
        self.assertEqual(403, status)

    def test_padded_username_cannot_bypass_login_rate_limit(self):
        for _ in range(10):
            self.assertEqual(401, self.request('/api/login', 'POST', {'username': 'throttle_missing', 'password': 'wrong'})[0])
        self.assertEqual(429, self.request('/api/login', 'POST', {'username': ' throttle_missing ', 'password': 'wrong'})[0])

    def test_malformed_json_is_reported(self):
        req = urllib.request.Request(self.base + '/api/login', data=b'{bad', headers={'Content-Type': 'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.client.open(req)
        self.assertEqual(400, ctx.exception.code)
        self.assertIn('error', json.loads(ctx.exception.read()))

    def test_deep_or_nonfinite_json_is_a_client_error(self):
        for raw in (b'{"username":' + b'[' * 3000 + b'0' + b']' * 3000 + b'}', b'{"username":NaN}'):
            req = urllib.request.Request(self.base + '/api/login', data=raw, headers={'Content-Type': 'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.client.open(req)
            self.assertEqual(400, ctx.exception.code)
            self.assertIn('error', json.loads(ctx.exception.read()))

    def test_crud_is_persistent_and_export_is_excel_compatible(self):
        self.login()
        status, record, _ = self.request('/api/records/departments', 'POST', {'code': 'HTTP_TEST', 'name': 'HTTP测试部门'})
        self.assertEqual(201, status, record)
        rid = record['id']
        status, updated, _ = self.request('/api/records/departments/' + str(rid), 'PUT', {'name': 'HTTP测试部门更新'})
        self.assertEqual(200, status, updated)
        status, records, _ = self.request('/api/records/departments?q=HTTP')
        self.assertEqual(200, status)
        self.assertTrue(any(r['id'] == rid and r['name'] == 'HTTP测试部门更新' for r in records['items']))
        status, csv, headers = self.request('/api/export/departments')
        self.assertEqual(200, status)
        self.assertTrue(csv.startswith(b'\xef\xbb\xbf'))
        self.assertIn('attachment', headers['Content-Disposition'])
        self.assertEqual(200, self.request('/api/records/departments/' + str(rid), 'DELETE')[0])

    def test_invalid_login_does_not_create_a_session(self):
        self.assertEqual(401, self.request('/api/login', 'POST', {'username': 'admin', 'password': 'wrong'})[0])
        self.assertEqual(401, self.request('/api/session')[0])

    def test_unknown_api_and_private_files_are_not_exposed(self):
        self.login()
        self.assertEqual(404, self.request('/api/unknown')[0])
        self.assertEqual(404, self.request('/app.py')[0])
        self.assertEqual(404, self.request('/data/hrm.db')[0])
        self.assertEqual(404, self.request('/%2e%2e/app.py')[0])

    def test_login_page_assets_are_available(self):
        status, html, _ = self.request('/')
        self.assertEqual(200, status)
        self.assertIn(b'/static/styles.css', html)
        self.assertEqual(200, self.request('/static/styles.css')[0])
        self.assertEqual(200, self.request('/static/app.js')[0])
        self.assertEqual(404, self.request('/static/%2e%2e/app.py')[0])

    def test_cross_origin_mutation_is_rejected(self):
        self.login()
        self.assertEqual(403, self.request('/api/records/departments', 'POST', {'name': '跨域'}, headers={'Origin': 'https://untrusted.example'})[0])

    def test_viewer_permissions_are_enforced_on_api(self):
        status, data, _ = self.request('/api/login', 'POST', {'username': 'viewer', 'password': 'View123456!'})
        self.assertEqual(200, status)
        self.csrf = data['csrf']
        self.assertEqual(200, self.request('/api/records/employees')[0])
        self.assertEqual(403, self.request('/api/records/users')[0])
        self.assertEqual(403, self.request('/api/export/payroll')[0])
        self.assertEqual(403, self.request('/api/records/departments', 'POST', {'name': '越权修改'})[0])


if __name__ == '__main__':
    unittest.main()
