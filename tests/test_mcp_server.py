import unittest
from pathlib import Path

from scripts.mcp_client import StdioMCPClient
from scripts.mcp_server import MCPServer


class MCPServerTests(unittest.TestCase):
    def setUp(self):
        self.server = MCPServer()

    def test_lists_hr_tools(self):
        response = self.server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        names = [tool['name'] for tool in response['result']['tools']]
        self.assertIn('search_policy_documents', names)
        self.assertIn('get_policy_section', names)
        self.assertIn('lookup_employee_profile', names)
        self.assertIn('check_pto_balance', names)
        self.assertIn('lookup_benefits_status', names)
        self.assertIn('create_mock_hr_ticket', names)
        self.assertIn('draft_hr_email', names)
        self.assertIn('check_policy_compliance', names)
        self.assertIn('retrieve_policy', names)
        self.assertIn('employee_record', names)
        self.assertIn('create_hr_ticket', names)

    def test_retrieve_policy_uses_local_rag_index(self):
        response = self.server.handle({
            'jsonrpc': '2.0',
            'id': 5,
            'method': 'tools/call',
            'params': {
                'name': 'retrieve_policy',
                'arguments': {'query': 'remote work eligibility', 'top_k': 1},
            },
        })
        result = response['result']['structuredContent']
        self.assertEqual(result['query'], 'remote work eligibility')
        self.assertEqual(len(result['results']), 1)
        self.assertEqual(result['results'][0]['source'], 'remote_work_policy.md')
        self.assertIn('manager approval', result['results'][0]['text'])

    def test_structured_employee_and_pto_tools(self):
        profile = self.server.handle({
            'jsonrpc': '2.0',
            'id': 6,
            'method': 'tools/call',
            'params': {
                'name': 'lookup_employee_profile',
                'arguments': {'employee_id': 'E-42'},
            },
        })
        balance = self.server.handle({
            'jsonrpc': '2.0',
            'id': 7,
            'method': 'tools/call',
            'params': {
                'name': 'check_pto_balance',
                'arguments': {'employee_id': 'E-42'},
            },
        })
        self.assertEqual(profile['result']['structuredContent']['employee_id'], 'E-42')
        self.assertIn('available_days', balance['result']['structuredContent'])

    def test_mock_ticket_tool_requires_confirmation(self):
        response = self.server.handle({
            'jsonrpc': '2.0',
            'id': 8,
            'method': 'tools/call',
            'params': {
                'name': 'create_mock_hr_ticket',
                'arguments': {'query': 'Create a benefits ticket'},
            },
        })
        self.assertEqual(response['result']['structuredContent']['status'], 'confirmation_required')

    def test_stdio_client_calls_the_real_mcp_server(self):
        client = StdioMCPClient(Path(__file__).resolve().parents[1] / 'scripts' / 'mcp_server.py')
        try:
            tool_names = [tool['name'] for tool in client.list_tools()]
            result = client.call_tool('retrieve_policy', {'query': 'PTO policy', 'top_k': 1})
        finally:
            client.close()

        self.assertIn('retrieve_policy', tool_names)
        self.assertEqual(result['results'][0]['source'], 'pto_policy.md')

    def test_requires_employee_id(self):
        response = self.server.handle({
            'jsonrpc': '2.0',
            'id': 2,
            'method': 'tools/call',
            'params': {'name': 'employee_record', 'arguments': {}},
        })
        self.assertEqual(response['error']['code'], -32602)
        self.assertIn('employee_id', response['error']['message'])

    def test_mutating_tool_is_mocked_without_confirmation(self):
        response = self.server.handle({
            'jsonrpc': '2.0',
            'id': 3,
            'method': 'tools/call',
            'params': {
                'name': 'create_hr_ticket',
                'arguments': {'query': 'Create a ticket'},
            },
        })
        self.assertTrue(response['result']['structuredContent']['mock'])
        self.assertEqual(response['result']['structuredContent']['status'], 'confirmation_required')

    def test_mutating_tool_executes_with_confirmation(self):
        response = self.server.handle({
            'jsonrpc': '2.0',
            'id': 4,
            'method': 'tools/call',
            'params': {
                'name': 'create_hr_ticket',
                'arguments': {'query': 'Create a ticket', 'confirmed': True},
            },
        })
        self.assertEqual(response['result']['structuredContent']['status'], 'created')


if __name__ == '__main__':
    unittest.main()
