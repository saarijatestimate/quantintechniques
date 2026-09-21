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
        self.synthesizer = synthesizer or self._default_synthesizer
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
        if workflow_name and 'retrieve_policy' in self.tools:
            tool_names = tuple(dict.fromkeys((*tool_names, 'retrieve_policy')))
            requires_tool = True
        clarification_question = self._clarification_question(normalized, workflow_name, requires_tool)
        clarification_required = clarification_question is not None

        if requires_tool and not tool_names and self.tools:
            tool_names = tuple(self.tools)
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
        arguments: Dict[str, Any] = {'query': query}
        required = spec.input_schema.get('required', [])
        employee_match = re.search(r'\b(?:employee\s*id|employee|eid)\s*[:#]?\s*([A-Za-z0-9-]+)', query, re.IGNORECASE)
        if employee_match:
            arguments['employee_id'] = employee_match.group(1)
        if confirmed:
            arguments['confirmed'] = True
        missing = [name for name in required if not arguments.get(name)]
        return arguments, missing

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
        matches = []
        for tool in self.tools.values():
            searchable = f'{tool.name} {tool.description}'.lower()
            if any(term in query for term in searchable.split()):
                matches.append(tool.name)
        return tuple(matches)

    @staticmethod
    def _default_synthesizer(prompt: str) -> str:
        return prompt
