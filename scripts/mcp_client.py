from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


class StdioMCPClient:
    """MCP client that calls tools through a local stdio server process."""

    def __init__(self, server_script: Optional[Path] = None) -> None:
        script = server_script or Path(__file__).with_name('mcp_server.py')
        self.process = subprocess.Popen(
            [sys.executable, str(script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._request_id = 0
        self._request('initialize', {
            'protocolVersion': '2025-06-18',
            'capabilities': {},
            'clientInfo': {'name': 'quantintechniques-agent', 'version': '1.0.0'},
        })
        self._notify('notifications/initialized')

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        response = self._request('tools/call', {'name': name, 'arguments': dict(arguments)})
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

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=5)

    def _request(self, method: str, params: Mapping[str, Any]) -> Dict[str, Any]:
        self._request_id += 1
        request = {
            'jsonrpc': '2.0',
            'id': self._request_id,
            'method': method,
            'params': dict(params),
        }
        if not self.process.stdin or not self.process.stdout:
            raise RuntimeError('MCP stdio process is not available')
        self.process.stdin.write(json.dumps(request) + '\n')
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            error = self.process.stderr.read() if self.process.stderr else ''
            raise RuntimeError(f'MCP server closed the connection: {error}')
        return json.loads(line)

    def _notify(self, method: str) -> None:
        if not self.process.stdin:
            raise RuntimeError('MCP stdio process is not available')
        self.process.stdin.write(json.dumps({
            'jsonrpc': '2.0',
            'method': method,
        }) + '\n')
        self.process.stdin.flush()
