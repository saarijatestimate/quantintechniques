import unittest

from app import app, close_mcp_client


class FlaskAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True)
        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        close_mcp_client()

    def test_app_starts_and_serves_chat_page(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'People Desk', response.data)
        self.assertIn(b'HR policy assistant', response.data)

    def test_health_endpoint_reports_app_status(self):
        response = self.client.get('/health')
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['app_status'], 'running')
        self.assertIn('mcp_connected', payload)


if __name__ == '__main__':
    unittest.main()
