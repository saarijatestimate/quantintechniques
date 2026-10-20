from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence

from scripts.prompt_builder import build_context_prompt
from scripts.retrieval import retrieve_top_k
from scripts.hr_workflows import detect_hr_workflow, start_workflow


class MCPToolClient(Protocol):
    """Minimal adapter for an MCP client exposing named tools."""

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        ...


class ToolSelector(Protocol):
    def __call__(self, intent: 'Intent', tools: Mapping[str, 'ToolSpec']) -> Sequence[str]:
        ...


class Synthesizer(Protocol):
    def __call__(self, prompt: str) -> str:
        ...


@dataclass(frozen=True)
class Intent:
    query: str
    requires_tool: bool
    tool_names: Sequence[str] = field(default_factory=tuple)
    reason: str = ''
    workflow_name: Optional[str] = None
    clarification_required: bool = False
    clarification_question: Optional[str] = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False


@dataclass
class OrchestrationResult:
    answer: str
    intent: Intent
    retrieved_chunks: List[Dict[str, Any]]
    tool_results: Dict[str, Any]
    prompt: str
    operational_trace: List[Dict[str, Any]] = field(default_factory=list)


class AgentOrchestrator:
    """Route a user request through RAG, MCP tools, and final response synthesis."""

    def __init__(
        self,
        *,
        chunks: Iterable[Dict[str, Any]],
        mcp_client: Optional[MCPToolClient] = None,
        tools: Iterable[ToolSpec] = (),
        synthesizer: Optional[Synthesizer] = None,
        top_k: int = 5,
        retrieval_filters: Optional[Dict[str, Any]] = None,
        query_rewrite: bool = False,
        rerank: bool = False,
        trace_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.chunks = list(chunks)
        self.mcp_client = mcp_client
        self.tools = {tool.name: tool for tool in tools}
        self.synthesizer = synthesizer
        self.top_k = top_k
        self.retrieval_filters = retrieval_filters
        self.query_rewrite = query_rewrite
        self.rerank = rerank
        self.trace_sink = trace_sink

    def run(self, query: str, *, confirmed: bool = False) -> OrchestrationResult:
        trace: List[Dict[str, Any]] = []
        intent = self.interpret_intent(query)
        self._record_trace(trace, 'intent', {
            'requires_tool': intent.requires_tool,
            'selected_tools': list(intent.tool_names),
            'workflow': intent.workflow_name,
            'decision': intent.reason,
            'clarification_required': intent.clarification_required,
        })
        retrieved = retrieve_top_k(
            self.chunks,
            query,
            top_k=self.top_k,
            filters=self.retrieval_filters,
            query_rewrite=self.query_rewrite,
            rerank=self.rerank,
        )
        evidence_complete, evidence_reason = self._policy_evidence_status(retrieved, intent)
        self._record_trace(trace, 'retrieval', {
            'top_k': self.top_k,
            'sources': [
                {'id': chunk.get('id'), 'source': chunk.get('source', 'unknown')}
                for chunk in retrieved
            ],
            'result_count': len(retrieved),
            'complete': evidence_complete,
            'completeness_reason': evidence_reason,
        })

        tool_results: Dict[str, Any] = {}
        if intent.clarification_required:
            self._record_trace(trace, 'clarification', {
                'question': intent.clarification_question,
            })
        elif intent.requires_tool:
            if self.mcp_client is None:
                self._record_trace(trace, 'tool_error', {
                    'error': 'MCP client is unavailable',
                    'selected_tools': list(intent.tool_names),
                })
            else:
                for tool_name in intent.tool_names:
                    if tool_name not in self.tools:
                        self._record_trace(trace, 'tool_error', {
                            'tool': tool_name,
                            'error': 'MCP tool is not registered',
                        })
                        continue
                    arguments, missing = self._tool_arguments(tool_name, query, confirmed)
                    if missing:
                        self._record_trace(trace, 'tool_error', {
                            'tool': tool_name,
                            'error': 'Required tool arguments are missing',
                            'missing_arguments': missing,
                        })
                        continue
                    if self._requires_confirmation(tool_name, confirmed):
                        tool_results[tool_name] = {
                            'mock': True,
                            'status': 'confirmation_required',
                            'tool': tool_name,
                            'arguments': arguments,
                        }
                        self._record_trace(trace, 'action_mocked', {
                            'tool': tool_name,
                            'arguments': arguments,
                            'reason': 'Explicit confirmation is required before a mutating action',
                        })
                        continue
                    self._record_trace(trace, 'tool_call', {
                        'tool': tool_name,
                        'arguments': arguments,
                    })
                    try:
                        tool_results[tool_name] = self.mcp_client.call_tool(tool_name, arguments)
                    except Exception as exc:  # MCP failures become traceable escalation signals.
                        self._record_trace(trace, 'tool_error', {
                            'tool': tool_name,
                            'error': str(exc),
                        })
                        continue
                    self._record_trace(trace, 'tool_result', {
                        'tool': tool_name,
                        'output': tool_results[tool_name],
                    })

        prompt = self.build_synthesis_prompt(query, retrieved, tool_results, intent)
        escalation, escalation_reason = self._escalation_decision(
            intent,
            retrieved,
            tool_results,
            evidence_complete,
            evidence_reason,
        )
        self._record_trace(trace, 'synthesis', {
            'answer_basis': {
                'retrieved_sources': [chunk.get('source', 'unknown') for chunk in retrieved],
                'tool_names': list(tool_results),
                'workflow': intent.workflow_name,
                'policy_evidence_complete': evidence_complete,
            },
            'escalation': escalation,
            'escalation_reason': escalation_reason,
        })
        if self.synthesizer is None:
            answer = self._default_synthesizer(
                query,
                retrieved,
                tool_results,
                intent,
                trace,
            )
        else:
            answer = self.synthesizer(prompt)
        return OrchestrationResult(answer, intent, retrieved, tool_results, prompt, trace)

    def _record_trace(self, trace: List[Dict[str, Any]], event: str, details: Dict[str, Any]) -> None:
        entry = {'event': event, **details}
        trace.append(entry)
        if self.trace_sink:
            self.trace_sink(entry)

    @staticmethod
    def _policy_evidence_status(
        retrieved: Sequence[Dict[str, Any]],
        intent: Intent,
    ) -> tuple[bool, str]:
        if not intent.workflow_name:
            return True, 'Policy evidence is not required for this route'
        usable = [
            chunk for chunk in retrieved
            if str(chunk.get('text') or chunk.get('content') or '').strip()
            and chunk.get('source')
        ]
        if not usable:
            return False, 'HR workflow has no usable policy chunk with text and source'
        return True, 'At least one usable policy source was retrieved'

    @staticmethod
    def _escalation_decision(
        intent: Intent,
        retrieved: Sequence[Dict[str, Any]],
        tool_results: Mapping[str, Any],
        evidence_complete: bool,
        evidence_reason: str,
    ) -> tuple[bool, str]:
        if intent.workflow_name and not evidence_complete:
            return True, evidence_reason
        if not retrieved and not tool_results:
            return True, 'No retrieved policy sources or tool results were available'
        if intent.requires_tool and not tool_results:
            return True, 'A tool was required but no tool result was produced'
        return False, 'Evidence and required tool results are available for synthesis'

    def interpret_intent(self, query: str) -> Intent:
        normalized = query.strip().lower()
        if not normalized:
            return Intent(
                query,
                False,
                reason='clarification required',
                clarification_required=True,
                clarification_question='What would you like help with? Please include the HR topic and your goal.',
            )

        workflow_name = detect_hr_workflow(normalized)
        tool_names = self._matching_tools(normalized)
        tool_terms = ('current', 'latest', 'live', 'today', 'lookup', 'search', 'send', 'create', 'update', 'delete')
        requires_tool = bool(tool_names) or any(term in normalized for term in tool_terms)
        if workflow_name:
            workflow_tools = []
            has_employee_id = self._employee_id(query) is not None
            if workflow_name == 'remote_work_eligibility':
                if has_employee_id and 'lookup_employee_profile' in self.tools:
                    workflow_tools.append('lookup_employee_profile')
                if 'check_policy_compliance' in self.tools:
                    workflow_tools.append('check_policy_compliance')
            elif workflow_name == 'pto_request' and has_employee_id and 'check_pto_balance' in self.tools:
                workflow_tools.append('check_pto_balance')
            if 'retrieve_policy' in self.tools:
                workflow_tools.append('retrieve_policy')
            tool_names = tuple(dict.fromkeys((*workflow_tools, *tool_names)))
            requires_tool = True
        clarification_question = self._clarification_question(normalized, workflow_name, requires_tool)
        if requires_tool and not tool_names and not workflow_name:
            clarification_question = (
                "I do not have a matching HR data or action tool for this request. "
                "Please contact HR or rephrase the request using an available HR workflow."
            )
        clarification_required = clarification_question is not None

        reason = 'clarification required' if clarification_required else ('HR workflow requires policy evidence and guided steps' if workflow_name else (
            'external or state-changing information requested' if requires_tool else 'retrieved context is sufficient'
        ))
        return Intent(
            query,
            requires_tool and not clarification_required,
            tool_names,
            reason,
            workflow_name,
            clarification_required,
            clarification_question,
        )

    def build_synthesis_prompt(
        self,
        query: str,
        retrieved_chunks: Iterable[Dict[str, Any]],
        tool_results: Mapping[str, Any],
        intent: Intent,
    ) -> str:
        rag_prompt = build_context_prompt(query, retrieved_chunks)
        workflow_context = ''
        if intent.workflow_name:
            workflow = start_workflow(intent.workflow_name)
            steps = '\n'.join(
                f'{index}. {step.name}: {step.question}'
                for index, step in enumerate(workflow.steps, start=1)
            )
            workflow_context = (
                f'\nHR workflow: {workflow.name}\n'
                f'Workflow objective: {workflow.description}\n'
                f'Workflow steps:\n{steps}\n'
            )
        tool_context = '\n'.join(
            f'[MCP tool: {name}]\n{result}' for name, result in tool_results.items()
        ) or 'No MCP tools were called.'
        return (
            f'{rag_prompt}\n'
            f'Routing decision: {intent.reason}.\n\n'
            f'Clarification request: {intent.clarification_question or "None"}\n\n'
            f'{workflow_context}\n'
            f'Tool results:\n{tool_context}\n\n'
            'Final response requirements:\n'
            '- Combine retrieved evidence and tool results only when relevant.\n'
            '- Clearly distinguish source-backed facts from tool output.\n'
            '- Do not claim a tool was called if it was not called.\n'
            '- If clarification is requested, ask only that question and wait for the user.\n'
            '- If evidence or tools are unavailable, explain the limitation and recommend escalation.\n'
        )

    def _tool_arguments(
        self,
        tool_name: str,
        query: str,
        confirmed: bool = False,
    ) -> tuple[Dict[str, Any], List[str]]:
        spec = self.tools[tool_name]
        required = spec.input_schema.get('required', [])
        properties = spec.input_schema.get('properties', {})
        arguments: Dict[str, Any] = {}
        if not properties or 'query' in properties or 'query' in required:
            arguments['query'] = query
        employee_id = self._employee_id(query)
        if employee_id and (
            not properties or 'employee_id' in properties or 'employee_id' in required
        ):
            arguments['employee_id'] = employee_id
        if confirmed and ('confirmed' in properties or 'confirmed' in required or not properties):
            arguments['confirmed'] = True
        missing = [name for name in required if not arguments.get(name)]
        return arguments, missing

    @staticmethod
    def _employee_id(query: str) -> Optional[str]:
        employee_match = re.search(
            r'\b(?:employee\s*id|eid)\s*[:#]?\s*([A-Za-z0-9-]+)'
            r'|\bemployee\s+([A-Za-z0-9-]*\d[A-Za-z0-9-]*)',
            query,
            re.IGNORECASE,
        )
        if not employee_match:
            return None
        return next(group for group in employee_match.groups() if group)

    def _requires_confirmation(self, tool_name: str, confirmed: bool) -> bool:
        if confirmed:
            return False
        tool = self.tools[tool_name]
        if tool.requires_confirmation:
            return True
        action_terms = (
            'create', 'update', 'delete', 'send', 'submit', 'ticket',
            'message', 'draft', 'record', 'change', 'approve',
        )
        searchable = f'{tool.name} {tool.description}'.lower()
        return any(term in searchable for term in action_terms)

    @staticmethod
    def _clarification_question(query: str, workflow_name: Optional[str], requires_tool: bool) -> Optional[str]:
        if workflow_name or requires_tool:
            return None
        generic_terms = ('hr', 'employee', 'benefits', 'policy', 'help', 'question', 'issue')
        if len(query.split()) <= 3 or any(query == term for term in generic_terms):
            return 'Could you clarify the HR topic and what outcome you need, such as eligibility, a request, or a policy explanation?'
        return None

    def _matching_tools(self, query: str) -> Sequence[str]:
        ignored_terms = {
            'a', 'an', 'and', 'are', 'as', 'at', 'by', 'check', 'current',
            'data', 'do', 'employee', 'for', 'get', 'hr', 'i', 'id', 'in', 'is', 'it', 'latest',
            'look', 'me', 'mock', 'my', 'of', 'on', 'or', 'please', 'policy',
            'request', 'the', 'to', 'up', 'with',
        }
        query_terms = set(re.findall(r'[a-z0-9]+', query.lower())) - ignored_terms
        matches = []
        for tool in self.tools.values():
            searchable = f'{tool.name} {tool.description}'.lower()
            tool_terms = set(re.findall(r'[a-z0-9]+', searchable)) - ignored_terms
            if query_terms & tool_terms:
                matches.append(tool.name)
        return tuple(matches)

    @staticmethod
    def _default_synthesizer(
        query: str,
        retrieved_chunks: Sequence[Dict[str, Any]],
        tool_results: Mapping[str, Any],
        intent: Intent,
        trace: Sequence[Dict[str, Any]],
    ) -> str:
        if intent.clarification_question:
            return intent.clarification_question

        lines: List[str] = []
        if intent.workflow_name == 'remote_work_eligibility':
            lines.append("I cannot confirm remote-work eligibility from the available information.")
            profile = tool_results.get('lookup_employee_profile')
            if profile:
                lines.append(
                    f"Profile (mock data): {profile.get('name', 'Employee')} is listed as "
                    f"{profile.get('employment_status', 'unknown')} in {profile.get('location', 'an unknown location')}."
                )
            lines.append("The retrieved policy says:")
            lines.extend(AgentOrchestrator._citation_lines(retrieved_chunks))
            compliance = tool_results.get('check_policy_compliance')
            if compliance:
                lines.append(
                    f"Compliance check (mock): {compliance.get('reason', 'This is not an authoritative HR decision.')}"
                )
            lines.append(
                "Next step: confirm the employing entity, role, manager approval, team coverage, and security requirements with HR. The available snippet does not establish Finland-specific eligibility."
            )
        elif intent.workflow_name == 'pto_request':
            balance = tool_results.get('check_pto_balance')
            if balance:
                lines.append(
                    f"Mock balance: {balance.get('available_days')} days available and "
                    f"{balance.get('pending_days')} pending as of {balance.get('as_of')}."
                )
            lines.append("The retrieved policy says:")
            lines.extend(AgentOrchestrator._citation_lines(retrieved_chunks))
            lines.append(
                "Next step: confirm the exact dates and PTO type, arrange a handover, and submit through the approved HR channel before leave begins. This guidance does not submit or approve a request."
            )
        else:
            lines.append("Here is what I found:")
            lines.extend(AgentOrchestrator._citation_lines(retrieved_chunks))
            for name, value in tool_results.items():
                lines.append(f"{name.replace('_', ' ').title()}: {AgentOrchestrator._format_tool_result(value)}")

        for event in trace:
            if event.get('event') == 'action_mocked':
                lines.append(
                    f"Confirmation required: {event['tool']} is a mock action and has not been submitted. Confirm only if you want to continue."
                )
            elif event.get('event') == 'tool_error':
                lines.append(f"Tool limitation: {event.get('error', 'The tool could not complete the request.')}")

        if not retrieved_chunks and not tool_results:
            lines.append("I could not find policy evidence or a tool result for this request. Please contact HR for help.")
        return '\n\n'.join(lines)

    @staticmethod
    def _citation_lines(chunks: Sequence[Dict[str, Any]]) -> List[str]:
        if not chunks:
            return ["- No matching policy source was retrieved."]
        return [
            f"- “{str(chunk.get('text') or chunk.get('content') or '').strip()}” "
            f"[{chunk.get('id', 'unlisted')}; {chunk.get('source', 'unknown')}; "
            f"{(chunk.get('metadata') or {}).get('section', 'section not specified')}]"
            for chunk in chunks
            if str(chunk.get('text') or chunk.get('content') or '').strip()
        ]

    @staticmethod
    def _format_tool_result(value: Any) -> str:
        if not isinstance(value, Mapping):
            return str(value)
        return '; '.join(f'{key.replace("_", " ")}: {item}' for key, item in value.items())
