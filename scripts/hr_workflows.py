from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence


@dataclass(frozen=True)
class WorkflowStep:
    name: str
    question: str
    required_fields: Sequence[str] = field(default_factory=tuple)


@dataclass
class WorkflowPlan:
    name: str
    description: str
    steps: List[WorkflowStep]
    current_step: int = 0
    answers: Dict[str, Any] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return self.current_step >= len(self.steps)

    @property
    def active_step(self) -> Optional[WorkflowStep]:
        if self.complete:
            return None
        return self.steps[self.current_step]

    def advance(self, answers: Mapping[str, Any]) -> WorkflowStep:
        if self.complete:
            raise ValueError(f'Workflow already complete: {self.name}')

        step = self.steps[self.current_step]
        missing = [field for field in step.required_fields if not answers.get(field)]
        if missing:
            raise ValueError(f'Missing required fields for {step.name}: {", ".join(missing)}')

        self.answers.update(answers)
        self.current_step += 1
        return self.active_step


WORKFLOWS = {
    'remote_work_eligibility': WorkflowPlan(
        name='remote_work_eligibility',
        description='Determine whether an employee is eligible to work remotely and identify approvals or restrictions.',
        steps=[
            WorkflowStep('employee_context', 'What is your role, employing entity, and primary work location?', ('role', 'work_location')),
            WorkflowStep('policy_eligibility', 'Does the applicable remote-work policy permit this role and location?', ('policy_evidence',)),
            WorkflowStep('team_coverage', 'Can team coverage, working hours, and manager approval be maintained?', ('manager_approval', 'coverage_plan')),
            WorkflowStep('security_readiness', 'Are the approved device, network, data-handling, and workspace controls available?', ('security_controls',)),
            WorkflowStep('decision', 'Summarize eligibility, conditions, required approvals, and escalation path.', ('role', 'work_location', 'policy_evidence', 'manager_approval', 'coverage_plan', 'security_controls')),
        ],
    ),
    'pto_request': WorkflowPlan(
        name='pto_request',
        description='Guide an employee through preparing and submitting a PTO request.',
        steps=[
            WorkflowStep('dates_and_type', 'What dates, duration, and PTO type are you requesting?', ('start_date', 'end_date', 'pto_type')),
            WorkflowStep('balance_and_policy', 'Is the requested time within your available balance and any blackout or notice rules?', ('balance_check', 'policy_evidence')),
            WorkflowStep('handover', 'What coverage and handover plan will keep critical work supported?', ('handover_plan',)),
            WorkflowStep('approval', 'Who must approve the request, and has the request been submitted through the approved channel?', ('approver', 'submission_channel')),
            WorkflowStep('confirmation', 'Confirm the request status, dates, approver, and any follow-up needed.', ('start_date', 'end_date', 'approver', 'submission_channel')),
        ],
    ),
}


def detect_hr_workflow(query: str) -> Optional[str]:
    normalized = query.lower()
    remote_terms = ('remote', 'work from home', 'wfh', 'telework')
    pto_terms = ('pto', 'paid time off', 'vacation day', 'time off', 'holiday leave')
    if any(term in normalized for term in remote_terms) and any(term in normalized for term in ('eligible', 'eligibility', 'can i', 'policy', 'approval')):
        return 'remote_work_eligibility'
    if any(term in normalized for term in pto_terms) and any(term in normalized for term in ('request', 'book', 'take', 'apply', 'policy', 'approval')):
        return 'pto_request'
    return None


def start_workflow(name: str) -> WorkflowPlan:
    if name not in WORKFLOWS:
        raise ValueError(f'Unknown HR workflow: {name}')
    template = WORKFLOWS[name]
    return WorkflowPlan(template.name, template.description, list(template.steps))
