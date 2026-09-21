from __future__ import annotations

import atexit
import os
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template, request

from scripts.mcp_client import StdioMCPClient
from scripts.http_mcp_client import HTTPMCPClient
from scripts.orchestrator import AgentOrchestrator, ToolSpec

ROOT = Path(__file__).resolve().parent
app = Flask(__name__)

POLICY_CHUNKS: List[Dict[str, Any]] = [
    {
        'id': 'remote-001',
        'source': 'remote_work_policy.md',
        'text': 'Remote work requires manager approval and an approved secure workspace.',
        'embedding': [1.0, 0.0],
        'metadata': {'topic': 'remote work', 'region': 'global'},
    },
    {
        'id': 'pto-001',
        'source': 'pto_policy.md',
        'text': 'PTO requests should be submitted through the approved HR channel before leave begins.',
        'embedding': [0.8, 0.2],
        'metadata': {'topic': 'PTO', 'region': 'global'},
    },
    {
        'id': 'benefits-001',
        'source': 'benefits_policy.md',
        'text': 'Benefits enrollment changes are handled during the annual enrollment window or after a qualifying life event.',
        'embedding': [0.6, 0.4],
        'metadata': {'topic': 'benefits', 'region': 'global'},
    },
]

TOOL_SPECS = [
    ToolSpec('retrieve_policy', 'retrieve HR policy evidence'),
    ToolSpec('lookup_employee_profile', 'look up employee profile'),
    ToolSpec('check_pto_balance', 'check PTO balance'),
    ToolSpec('lookup_benefits_status', 'look up benefits status'),
    ToolSpec('create_mock_hr_ticket', 'create a mock HR ticket'),
    ToolSpec('draft_hr_email', 'draft an HR email'),
    ToolSpec('check_policy_compliance', 'check policy compliance'),
]

DEMO_TASKS = {
    'remote-work-eligibility': {
        'title': 'Remote-work eligibility',
        'message': 'Am I eligible to work remote from Finland?',
        'purpose': 'Runs the remote-work eligibility workflow with retrieved policy evidence.',
    },
    'pto-request-guidance': {
        'title': 'PTO request guidance',
        'message': 'How do I request PTO for next week?',
        'purpose': 'Runs the multi-step PTO request workflow and policy retrieval.',
    },
}

_mcp_client = None


def get_mcp_client():
    global _mcp_client
    if _mcp_client is None:
        try:
            mcp_server_url = os.getenv('MCP_SERVER_URL', '').strip()
            if mcp_server_url:
                _mcp_client = HTTPMCPClient(mcp_server_url)
            else:
                _mcp_client = StdioMCPClient(ROOT / 'scripts' / 'mcp_server.py')
        except Exception:
            _mcp_client = False
    return _mcp_client or None


def create_agent() -> AgentOrchestrator:
    return AgentOrchestrator(
        chunks=POLICY_CHUNKS,
        mcp_client=get_mcp_client(),
        tools=TOOL_SPECS,
        top_k=5,
        query_rewrite=True,
        rerank=True,
    )


@app.get('/')
def index():
    return render_template('chat.html')


@app.get('/api/demo/tasks')
def demo_tasks():
    return jsonify({'tasks': DEMO_TASKS})


@app.post('/chat')
@app.post('/api/chat')
def chat():
    payload = request.get_json(silent=True) or {}
    query = str(payload.get('message', '')).strip()
    confirmed = bool(payload.get('confirmed', False))
    if not query:
        return jsonify({'error': 'Please enter an HR question.'}), 400

    try:
        result = create_agent().run(query, confirmed=confirmed)
    except Exception as exc:
        return jsonify({
            'answer': 'I could not complete that request. Please try again or contact HR.',
            'error': str(exc),
            'trace': [{'event': 'web_error', 'error': str(exc)}],
        }), 503

    needs_confirmation = any(
        value.get('status') == 'confirmation_required'
        for value in result.tool_results.values()
        if isinstance(value, dict)
    )
    citations = [
        {
            'id': chunk.get('id'),
            'source': chunk.get('source', 'unknown'),
            'metadata': chunk.get('metadata', {}),
        }
        for chunk in result.retrieved_chunks
    ]
    snippets = [
        {
            'id': chunk.get('id'),
            'source': chunk.get('source', 'unknown'),
            'text': chunk.get('text') or chunk.get('content', ''),
        }
        for chunk in result.retrieved_chunks
    ]
    concise_trace = [
        {
            'event': event.get('event'),
            **{
                key: event[key]
                for key in ('tool', 'arguments', 'output', 'selected_tools', 'sources', 'escalation', 'escalation_reason')
                if key in event
            },
        }
        for event in result.operational_trace
    ]
    return jsonify({
        'answer': result.answer,
        'workflow': result.intent.workflow_name,
        'citations': citations,
        'snippets': snippets,
        'sources': citations,
        'tool_results': result.tool_results,
        'trace': concise_trace,
        'confirmation_required': needs_confirmation,
    })


@app.post('/api/demo/<task_id>')
def run_demo(task_id):
    task = DEMO_TASKS.get(task_id)
    if task is None:
        return jsonify({'error': f'Unknown demo task: {task_id}'}), 404
    request_payload = request.get_json(silent=True) or {}
    with app.test_request_context(
        '/chat',
        method='POST',
        json={'message': task['message'], 'confirmed': bool(request_payload.get('confirmed', False))},
    ):
        return chat()


@app.get('/health')
@app.get('/api/health')
def health():
    mcp_connected = get_mcp_client() is not None
    mcp_transport = 'http' if os.getenv('MCP_SERVER_URL', '').strip() else 'stdio'
    return jsonify({
        'status': 'ok',
        'app_status': 'running',
        'mcp_connected': mcp_connected,
        'mcp_status': 'connected' if mcp_connected else 'unavailable',
        'mcp_transport': mcp_transport,
        'mcp_server_url_configured': bool(os.getenv('MCP_SERVER_URL', '').strip()),
    })


@atexit.register
def close_mcp_client():
    if _mcp_client and hasattr(_mcp_client, 'close'):
        _mcp_client.close()


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
