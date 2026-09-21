from __future__ import annotations

from flask import Flask, jsonify, request

from scripts.mcp_server import MCPServer

app = Flask(__name__)
server = MCPServer()


@app.get('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'hr-mcp', 'transport': 'http'})


@app.post('/mcp')
def mcp():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(MCPServer._error(None, -32700, 'Request body must be a JSON object')), 400

    response = server.handle(payload)
    if response is None:
        return ('', 204)
    return jsonify(response)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
