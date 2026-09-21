from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping

try:
    from scripts.retrieval import retrieve_top_k
except ModuleNotFoundError:
    from retrieval import retrieve_top_k


POLICY_INDEX = [
    {
        'id': 'remote-001',
        'source': 'remote_work_policy.md',
        'text': 'Remote work requires manager approval and an approved secure workspace.',
        'metadata': {'topic': 'remote work', 'region': 'global'},
    },
    {
        'id': 'pto-001',
        'source': 'pto_policy.md',
        'text': 'PTO requests should be submitted through the approved HR channel before leave begins.',
        'metadata': {'topic': 'PTO', 'region': 'global'},
    },
]


@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    mutating: bool = False


TOOLS = (
    MCPTool(
        'search_policy_documents',
        'Search HR policy documents in the local RAG index.',
        {
            'type': 'object',
            'properties': {'query': {'type': 'string'}, 'top_k': {'type': 'integer'}},
            'required': ['query'],
        },
    ),
    MCPTool(
        'get_policy_section',
        'Retrieve a specific section of an HR policy document.',
        {
            'type': 'object',
            'properties': {'source': {'type': 'string'}, 'section': {'type': 'string'}},
            'required': ['source', 'section'],
        },
    ),
    MCPTool(
        'retrieve_policy',
        'Retrieve relevant HR policy evidence from the local RAG index.',
        {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'},
                'top_k': {'type': 'integer', 'minimum': 1, 'maximum': 10},
            },
            'required': ['query'],
        },
    ),
    MCPTool(
        'lookup_employee_profile',
        'Look up mock employee profile data by employee ID.',
        {
            'type': 'object',
            'properties': {'employee_id': {'type': 'string'}},
            'required': ['employee_id'],
        },
    ),
    MCPTool(
        'check_pto_balance',
        'Check mock PTO balance for an employee.',
        {
            'type': 'object',
            'properties': {'employee_id': {'type': 'string'}},
            'required': ['employee_id'],
        },
    ),
    MCPTool(
        'lookup_benefits_status',
        'Look up mock benefits enrollment status for an employee.',
        {
            'type': 'object',
            'properties': {'employee_id': {'type': 'string'}},
            'required': ['employee_id'],
        },
    ),
    MCPTool(
        'create_mock_hr_ticket',
        'Create a mock HR ticket. Requires explicit confirmation.',
        {
            'type': 'object',
            'properties': {'query': {'type': 'string'}, 'employee_id': {'type': 'string'}, 'confirmed': {'type': 'boolean'}},
            'required': ['query'],
        },
        mutating=True,
    ),
    MCPTool(
        'draft_hr_email',
        'Draft a mock HR email. Requires explicit confirmation before producing an outbound draft.',
        {
            'type': 'object',
            'properties': {'query': {'type': 'string'}, 'confirmed': {'type': 'boolean'}},
            'required': ['query'],
        },
        mutating=True,
    ),
    MCPTool(
        'check_policy_compliance',
        'Check mock compliance of an HR request against retrieved policy evidence.',
        {
            'type': 'object',
            'properties': {'query': {'type': 'string'}, 'policy_source': {'type': 'string'}},
            'required': ['query'],
        },
    ),
    MCPTool(
        'order_status',
        'Check the current status of an order.',
        {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']},
    ),
    MCPTool(
        'employee_record',
        'Look up an employee record by employee ID.',
        {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'},
                'employee_id': {'type': 'string'},
            },
            'required': ['employee_id'],
        },
    ),
    MCPTool(
        'create_hr_ticket',
        'Create an HR ticket. Requires explicit confirmation.',
        {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'},
                'employee_id': {'type': 'string'},
                'confirmed': {'type': 'boolean'},
            },
            'required': ['query'],
        },
        mutating=True,
    ),
    MCPTool(
        'update_case_record',
        'Update an HR case record. Requires explicit confirmation.',
        {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'},
                'employee_id': {'type': 'string'},
                'confirmed': {'type': 'boolean'},
            },
            'required': ['query', 'employee_id'],
        },
        mutating=True,
    ),
)


class MCPServer:
    def __init__(self, tools: Iterable[MCPTool] = TOOLS) -> None:
        self.tools = {tool.name: tool for tool in tools}

    def handle(self, request: Mapping[str, Any]) -> Dict[str, Any] | None:
        method = request.get('method')
        request_id = request.get('id')

        if request_id is None and method == 'notifications/initialized':
            return None
        if method == 'initialize':
            return self._result(request_id, {
                'protocolVersion': '2025-06-18',
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'quantintechniques-hr', 'version': '1.0.0'},
            })
        if method == 'tools/list':
            return self._result(request_id, {
                'tools': [
                    {
                        'name': tool.name,
                        'description': tool.description,
                        'inputSchema': tool.input_schema,
                    }
                    for tool in self.tools.values()
                ]
            })
        if method == 'tools/call':
            return self._call_tool(request_id, request.get('params') or {})
        if method == 'ping':
            return self._result(request_id, {})
        return self._error(request_id, -32601, f'Unknown MCP method: {method}')

    def _call_tool(self, request_id: Any, params: Mapping[str, Any]) -> Dict[str, Any]:
        name = params.get('name')
        arguments = params.get('arguments') or {}
        tool = self.tools.get(name)
        if tool is None:
            return self._error(request_id, -32602, f'Unknown MCP tool: {name}')

        missing = [field for field in tool.input_schema.get('required', []) if not arguments.get(field)]
        if missing:
            return self._error(request_id, -32602, f'Missing required arguments: {", ".join(missing)}')

        if tool.mutating and arguments.get('confirmed') is not True:
            result = {
                'mock': True,
                'status': 'confirmation_required',
                'tool': name,
                'arguments': dict(arguments),
            }
        elif name in ('search_policy_documents', 'retrieve_policy'):
            matches = retrieve_top_k(
                POLICY_INDEX,
                arguments['query'],
                top_k=min(int(arguments.get('top_k', 5)), 10),
            )
            result = {
                'query': arguments['query'],
                'results': [
                    {
                        'id': chunk.get('id'),
                        'source': chunk.get('source'),
                        'text': chunk.get('text'),
                        'metadata': chunk.get('metadata', {}),
                    }
                    for chunk in matches
                ],
            }
        elif name == 'get_policy_section':
            matches = [
                chunk for chunk in POLICY_INDEX
                if chunk['source'] == arguments['source']
                and arguments['section'].lower() in chunk['text'].lower()
            ]
            result = {
                'source': arguments['source'],
                'section': arguments['section'],
                'results': matches,
            }
        elif name == 'lookup_employee_profile':
            result = {
                'employee_id': arguments['employee_id'],
                'name': 'Mock Employee',
                'department': 'People Operations',
                'location': 'Helsinki',
                'employment_status': 'active',
            }
        elif name == 'check_pto_balance':
            result = {
                'employee_id': arguments['employee_id'],
                'available_days': 18,
                'pending_days': 2,
                'as_of': '2026-09-21',
            }
        elif name == 'lookup_benefits_status':
            result = {
                'employee_id': arguments['employee_id'],
                'medical': 'enrolled',
                'dental': 'enrolled',
                'retirement': 'enrolled',
            }
        elif name == 'draft_hr_email':
            result = {
                'status': 'drafted',
                'subject': 'HR request follow-up',
                'body': 'Mock draft only. Review and approve before sending.',
            }
        elif name == 'check_policy_compliance':
            result = {
                'compliant': True,
                'status': 'mock_check',
                'policy_source': arguments.get('policy_source', 'not specified'),
                'reason': 'Mock result; verify against current HR policy before acting.',
            }
        elif name == 'order_status':
            result = {'status': 'shipped', 'order_id': 'A-100'}
        elif name == 'employee_record':
            result = {'employee_id': arguments['employee_id'], 'status': 'active'}
        elif name == 'create_hr_ticket':
            result = {'ticket_id': f'HR-{uuid.uuid4().hex[:8].upper()}', 'status': 'created'}
        elif name == 'create_mock_hr_ticket':
            result = {'ticket_id': f'HR-{uuid.uuid4().hex[:8].upper()}', 'status': 'created_mock'}
        elif name == 'update_case_record':
            result = {'employee_id': arguments['employee_id'], 'status': 'updated'}
        else:
            return self._error(request_id, -32602, f'No handler for MCP tool: {name}')

        return self._result(request_id, {
            'content': [{'type': 'text', 'text': json.dumps(result, sort_keys=True)}],
            'structuredContent': result,
        })

    @staticmethod
    def _result(request_id: Any, result: Mapping[str, Any]) -> Dict[str, Any]:
        return {'jsonrpc': '2.0', 'id': request_id, 'result': result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}


def main() -> None:
    server = MCPServer()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = server.handle(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + '\n')
                sys.stdout.flush()
        except json.JSONDecodeError as exc:
            response = MCPServer._error(None, -32700, f'Invalid JSON: {exc.msg}')
            sys.stdout.write(json.dumps(response) + '\n')
            sys.stdout.flush()


if __name__ == '__main__':
    main()
