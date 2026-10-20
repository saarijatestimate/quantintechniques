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

    def test_remote_work_demo_uses_profile_policy_and_compliance_tools(self):
        response = self.client.post('/api/demo/remote-work-eligibility', json={})
        payload = response.get_json()
        calls = [event for event in payload['trace'] if event['event'] == 'tool_call']

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [event['tool'] for event in calls],
            ['lookup_employee_profile', 'check_policy_compliance', 'retrieve_policy'],
        )
        self.assertEqual(calls[0]['arguments'], {'employee_id': 'DEMO-1002'})
        self.assertEqual(
            calls[1]['arguments'],
            {'query': 'Am I eligible to work remote from Finland? employee ID DEMO-1002'},
        )
        self.assertEqual(payload['tool_results']['lookup_employee_profile']['location'], 'Helsinki')
        self.assertTrue(payload['tool_results']['check_policy_compliance']['compliant'])
        self.assertIn('cannot confirm remote-work eligibility', payload['answer'])
        self.assertIn('[remote-001; remote_work_policy.md; Remote work]', payload['answer'])
        self.assertNotIn('User question:', payload['answer'])

    def test_pto_demo_uses_balance_search_and_retrieval_tools(self):
        response = self.client.post('/api/demo/pto-request-guidance', json={})
        payload = response.get_json()
        calls = [event for event in payload['trace'] if event['event'] == 'tool_call']

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [event['tool'] for event in calls],
            ['check_pto_balance', 'retrieve_policy', 'search_policy_documents'],
        )
        self.assertEqual(calls[0]['arguments'], {'employee_id': 'DEMO-1002'})
        self.assertEqual(
            calls[1]['arguments'],
            {'query': 'Search the PTO policy and check my balance for next week. employee ID DEMO-1002'},
        )
        self.assertEqual(payload['tool_results']['check_pto_balance']['available_days'], 18)
        self.assertIn('[pto-001; pto_policy.md; PTO requests]', payload['answer'])
        self.assertIn('does not submit or approve a request', payload['answer'])
        self.assertNotIn('User question:', payload['answer'])

    def test_mock_ticket_action_waits_for_confirmation(self):
        message = 'Create a mock HR ticket for my PTO question. employee ID DEMO-1002'

        preview = self.client.post('/api/chat', json={'message': message})
        preview_payload = preview.get_json()
        self.assertTrue(preview_payload['confirmation_required'])
        self.assertTrue(any(event['event'] == 'action_mocked' for event in preview_payload['trace']))
        self.assertFalse(any(
            event.get('event') == 'tool_call' and event.get('tool') == 'create_mock_hr_ticket'
            for event in preview_payload['trace']
        ))

        confirmed = self.client.post('/api/chat', json={'message': message, 'confirmed': True})
        confirmed_payload = confirmed.get_json()
        self.assertFalse(confirmed_payload['confirmation_required'])
        self.assertEqual(confirmed_payload['tool_results']['create_mock_hr_ticket']['status'], 'created_mock')
        self.assertTrue(any(
            event.get('event') == 'tool_call' and event.get('tool') == 'create_mock_hr_ticket'
            for event in confirmed_payload['trace']
        ))


if __name__ == '__main__':
    unittest.main()
