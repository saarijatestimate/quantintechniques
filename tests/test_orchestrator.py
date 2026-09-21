import unittest

from scripts.orchestrator import AgentOrchestrator, ToolSpec


class FakeMCPClient:
    def __init__(self):
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {'status': 'shipped', 'order_id': 'A-100'}


class FailingMCPClient(FakeMCPClient):
    def call_tool(self, name, arguments):
        raise ConnectionError('MCP server unavailable')


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.chunks = [
            {
                'id': 1,
                'source': 'policy.md',
                'text': 'Refunds are processed within 30 days.',
                'embedding': [1.0, 0.0],
                'metadata': {'section': 'refunds'},
            }
        ]

    def test_rag_sufficient_does_not_call_mcp(self):
        client = FakeMCPClient()
        agent = AgentOrchestrator(
            chunks=self.chunks,
            mcp_client=client,
            tools=[ToolSpec('order_status', 'check current order status')],
            synthesizer=lambda prompt: prompt,
        )

        result = agent.run('What is the refund policy?')

        self.assertFalse(result.intent.requires_tool)
        self.assertEqual(client.calls, [])
        self.assertIn('policy.md', result.answer)
        self.assertEqual(
            [event['event'] for event in result.operational_trace],
            ['intent', 'retrieval', 'synthesis'],
        )
        self.assertEqual(result.operational_trace[1]['sources'][0]['source'], 'policy.md')
        self.assertFalse(result.operational_trace[2]['escalation'])

    def test_external_request_calls_matching_mcp_tool(self):
        client = FakeMCPClient()
        agent = AgentOrchestrator(
            chunks=self.chunks,
            mcp_client=client,
            tools=[ToolSpec('order_status', 'check current order status')],
            synthesizer=lambda prompt: prompt,
        )

        result = agent.run('What is the latest order status?')

        self.assertTrue(result.intent.requires_tool)
        self.assertEqual(client.calls, [('order_status', {'query': 'What is the latest order status?'})])
        self.assertIn('shipped', result.prompt)
        tool_call = result.operational_trace[2]
        tool_result = result.operational_trace[3]
        synthesis = result.operational_trace[4]
        self.assertEqual(tool_call['event'], 'tool_call')
        self.assertEqual(tool_call['arguments']['query'], 'What is the latest order status?')
        self.assertEqual(tool_result['output']['status'], 'shipped')
        self.assertEqual(synthesis['answer_basis']['tool_names'], ['order_status'])

    def test_trace_sink_receives_operational_events(self):
        events = []
        agent = AgentOrchestrator(
            chunks=[],
            trace_sink=events.append,
            synthesizer=lambda prompt: prompt,
        )

        result = agent.run('What is the policy?')

        self.assertEqual(events, result.operational_trace)
        self.assertTrue(events[-1]['escalation'])

    def test_missing_employee_id_skips_tool_call_and_escalates(self):
        client = FakeMCPClient()
        agent = AgentOrchestrator(
            chunks=self.chunks,
            mcp_client=client,
            tools=[ToolSpec(
                'employee_record',
                'look up employee record',
                {'required': ['employee_id']},
            )],
            synthesizer=lambda prompt: prompt,
        )

        result = agent.run('Look up the employee record')

        self.assertEqual(client.calls, [])
        self.assertTrue(any(event['event'] == 'tool_error' for event in result.operational_trace))
        self.assertTrue(result.operational_trace[-1]['escalation'])

    def test_unavailable_mcp_is_reported_without_crashing(self):
        agent = AgentOrchestrator(
            chunks=self.chunks,
            mcp_client=FailingMCPClient(),
            tools=[ToolSpec('order_status', 'check current order status')],
            synthesizer=lambda prompt: prompt,
        )

        result = agent.run('What is the latest order status?')

        self.assertIn('MCP server unavailable', str(result.operational_trace))
        self.assertTrue(result.operational_trace[-1]['escalation'])

    def test_ambiguous_request_asks_for_clarification(self):
        agent = AgentOrchestrator(chunks=[], synthesizer=lambda prompt: prompt)

        result = agent.run('HR help')

        self.assertTrue(result.intent.clarification_required)
        self.assertIn('clarify', result.intent.clarification_question.lower())
        self.assertIn(result.intent.clarification_question, result.answer)

    def test_hr_workflow_with_incomplete_policy_evidence_escalates(self):
        agent = AgentOrchestrator(
            chunks=[{'id': 9, 'text': 'A fragment without a source reference.', 'embedding': [1.0, 0.0]}],
            synthesizer=lambda prompt: prompt,
        )

        result = agent.run('Am I eligible to work remote?')

        retrieval = result.operational_trace[1]
        synthesis = result.operational_trace[-1]
        self.assertFalse(retrieval['complete'])
        self.assertTrue(synthesis['escalation'])
        self.assertIn('usable policy chunk', synthesis['escalation_reason'])

    def test_mutating_action_is_mocked_without_confirmation(self):
        client = FakeMCPClient()
        agent = AgentOrchestrator(
            chunks=self.chunks,
            mcp_client=client,
            tools=[ToolSpec('create_hr_ticket', 'create an HR ticket')],
            synthesizer=lambda prompt: prompt,
        )

        result = agent.run('Create an HR ticket for my leave issue')

        self.assertEqual(client.calls, [])
        self.assertEqual(result.tool_results['create_hr_ticket']['mock'], True)
        self.assertEqual(result.tool_results['create_hr_ticket']['status'], 'confirmation_required')
        self.assertTrue(any(event['event'] == 'action_mocked' for event in result.operational_trace))

    def test_mutating_action_runs_only_after_explicit_confirmation(self):
        client = FakeMCPClient()
        agent = AgentOrchestrator(
            chunks=self.chunks,
            mcp_client=client,
            tools=[ToolSpec('update_case_record', 'update an HR case record')],
            synthesizer=lambda prompt: prompt,
        )

        result = agent.run('Update the case record for employee E-42', confirmed=True)

        self.assertEqual(client.calls, [(
            'update_case_record',
            {
                'query': 'Update the case record for employee E-42',
                'employee_id': 'E-42',
                'confirmed': True,
            },
        )])
        self.assertEqual(result.tool_results['update_case_record']['status'], 'shipped')


if __name__ == '__main__':
    unittest.main()
