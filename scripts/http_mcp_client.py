from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Mapping


class HTTPMCPClient:
    """MCP client that sends JSON-RPC requests to an HTTP MCP service."""

    def __init__(self, base_url: str) -> None:
        normalized_url = base_url.strip().rstrip('/')
        if not normalized_url.startswith(('http://', 'https://')):
            normalized_url = f'https://{normalized_url}'
        self.base_url = normalized_url
        self._request_id = 0

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        response = self._request('tools/call', {
            'name': name,
            'arguments': dict(arguments),
        })
        if 'error' in response:
            error = response['error']
            raise RuntimeError(f"MCP tool error {error.get('code')}: {error.get('message')}")
        result = response.get('result', {})
        return result.get('structuredContent', result)

    def list_tools(self) -> Any:
        response = self._request('tools/list', {})
        if 'error' in response:
            raise RuntimeError(response['error'].get('message', 'MCP tools/list failed'))
        return response.get('result', {}).get('tools', [])

    def _request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        payload = json.dumps({
            'jsonrpc': '2.0',
            'id': self._request_id,
            'method': method,
            'params': dict(params),
        }).encode('utf-8')
        request = urllib.request.Request(
            f'{self.base_url}/mcp',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.URLError as exc:
            raise RuntimeError(f'MCP HTTP service unavailable: {exc.reason}') from exc
