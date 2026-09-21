import unittest

from scripts.hr_workflows import detect_hr_workflow, start_workflow
from scripts.orchestrator import AgentOrchestrator


class HRWorkflowTests(unittest.TestCase):
    def test_detects_remote_work_eligibility(self):
        self.assertEqual(
            detect_hr_workflow('Am I eligible to work remote from Finland?'),
            'remote_work_eligibility',
        )

    def test_detects_pto_request(self):
        self.assertEqual(
            detect_hr_workflow('How do I request PTO for next week?'),
            'pto_request',
        )

    def test_workflow_requires_step_fields_and_advances(self):
        workflow = start_workflow('pto_request')

        with self.assertRaises(ValueError):
            workflow.advance({'start_date': '2026-10-01'})

        workflow.advance({
            'start_date': '2026-10-01',
            'end_date': '2026-10-03',
            'pto_type': 'vacation',
        })
        self.assertEqual(workflow.current_step, 1)
        self.assertEqual(workflow.active_step.name, 'balance_and_policy')

    def test_orchestrator_includes_hr_workflow_steps(self):
        agent = AgentOrchestrator(
            chunks=[{
                'id': 1,
                'source': 'hr_policy.md',
                'text': 'Remote work requires manager approval.',
                'embedding': [1.0, 0.0],
            }],
            synthesizer=lambda prompt: prompt,
        )

        result = agent.run('Am I eligible to work remote?')

        self.assertEqual(result.intent.workflow_name, 'remote_work_eligibility')
        self.assertIn('Workflow steps:', result.prompt)
        self.assertIn('security_readiness', result.prompt)


if __name__ == '__main__':
    unittest.main()
