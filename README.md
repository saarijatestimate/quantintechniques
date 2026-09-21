# Environment selector project

This project includes separate environment files for:

- int
- syst
- accept

## Continuous integration

GitHub Actions runs the Python test suite for every push and pull request. The workflow tests Python 3.11 and 3.12, installs [requirements.txt](requirements.txt), and runs all files matching `tests/test_*.py`.

The automated coverage includes:

- [tests/test_app.py](tests/test_app.py), which starts the Flask app through its test client and verifies `/` and `/health`.
- [tests/test_mcp_server.py](tests/test_mcp_server.py), which discovers tools through `tools/list` and calls `retrieve_policy` through the real stdio MCP client/server path.

Workflow file: [.github/workflows/ci.yml](.github/workflows/ci.yml)

## Flask HR chat app

The project includes a Flask web app for HR policy and workflow questions. It uses the existing orchestrator, local RAG policy chunks, and the stdio MCP client. The interface shows the assistant response, retrieved sources, operational trace, and confirmation prompts for protected actions.

Install dependencies and start the app from the project root:

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in a browser.

### Deploy to Render free tier

The repository includes [render.yaml](render.yaml) for two zero-cost Render web services: the Flask web app and a separate HTTP MCP service. To deploy them, push this repository to GitHub, open the Render dashboard, choose **New > Blueprint**, connect the repository, and apply the `render.yaml` blueprint. Render will install the dependencies and start both services on their platform-provided ports.

The web service receives the MCP service host through `MCP_SERVER_URL`. The HTTP client normalizes that host to HTTPS and calls the MCP JSON-RPC endpoint at `/mcp`. When `MCP_SERVER_URL` is absent locally, the app falls back to the stdio MCP server.

After deployment, Render provides a shareable URL in this form:

```text
https://quantintechniques-hr.onrender.com
```

Verify the deployment with:

```powershell
curl https://quantintechniques-hr.onrender.com/health
curl https://quantintechniques-hr.onrender.com/api/demo/tasks
```

The MCP service health endpoint follows the second service's generated hostname:

```powershell
curl https://quantintechniques-hr-mcp.onrender.com/health
```

#### Free-tier cold start

Both Render services can spin down after inactivity. The first request after sleeping wakes the web service, and the first MCP-backed request may also wake the separate MCP service. Expect the first health check or demo request to take longer than normal, or briefly return a gateway/timeout response while the services start.

For a reliable demo run:

1. Open the web URL or call `/health` once to wake the web service.
2. Wait for `app_status=running` and `mcp_status=connected`.
3. If the MCP status is temporarily unavailable, wait briefly and retry `/health`.
4. Run the demo task after the health response shows both services are connected.

The deployment requires the repository owner to connect a GitHub account to Render; no deployment credential or public hosting account is available from this workspace.

The main endpoints are:

- `GET /` renders the chat interface.
- `POST /chat` or `POST /api/chat` accepts `{ "message": "...", "confirmed": false }` and returns the final answer, citations, retrieved snippets, tool results, and a concise tool-call trace.
- `GET /health` or `GET /api/health` returns app status and whether the local MCP process is connected.

### Reproducible demo tasks

The UI includes buttons for two agentic demos:

- **Remote-work eligibility**: retrieves remote-work policy evidence and runs the eligibility workflow.
- **PTO request guidance**: retrieves PTO policy evidence and runs the multi-step request workflow.

The demo buttons show a loading state while a sleeping free-tier service wakes up. If the first request times out, retry the same demo after checking `/health`; this is expected cold-start behavior, not a different workflow result.

API clients can discover the demos:

```powershell
curl http://127.0.0.1:5000/api/demo/tasks
```

Run either demo through the same chat/orchestration path:

```powershell
curl -X POST http://127.0.0.1:5000/api/demo/remote-work-eligibility `
    -H "Content-Type: application/json" -d "{\"confirmed\":false}"

curl -X POST http://127.0.0.1:5000/api/demo/pto-request-guidance `
    -H "Content-Type: application/json" -d "{\"confirmed\":false}"
```

Each response contains the final `answer`, `citations`, `snippets`, `tool_results`, and concise `trace`. The demo endpoints do not bypass confirmation safety; protected actions remain mocked unless explicitly confirmed.

Example health response:

```json
{
    "status": "ok",
    "app_status": "running",
    "mcp_connected": true,
    "mcp_status": "connected"
}
```

Example response shape:

```json
{
    "answer": "Remote work requires manager approval...",
    "citations": [{"id": "remote-001", "source": "remote_work_policy.md", "metadata": {"topic": "remote work"}}],
    "snippets": [{"id": "remote-001", "source": "remote_work_policy.md", "text": "Remote work requires manager approval..."}],
    "trace": [{"event": "tool_call", "tool": "retrieve_policy", "arguments": {"query": "remote work"}}]
}
```

## Local vector database for embedded chunks

The project can use PostgreSQL with the pgvector extension as a lightweight local vector store for embedded chunks.

### Start PostgreSQL with pgvector

```bash
docker compose up -d
python scripts/init_vector_db.py
```

This starts a local PostgreSQL instance using the `pgvector/pgvector` image and initializes the database and table used for storing chunk metadata and vector embeddings.

## Files

- `env/int.env`
- `env/syst.env`
- `env/accept.env`
- `.env` is the active environment file
- `scripts/select_env.py` copies the selected environment into `.env`
- `scripts/init_vector_db.py` initializes PostgreSQL + pgvector
- `scripts/orchestrator.py` routes requests through RAG and MCP tools
- `scripts/mcp_server.py` exposes local HR tools over MCP stdio
- `scripts/hr_workflows.py` provides remote-work eligibility and PTO request workflows
- `docker-compose.yml` defines the local database service

## Select an environment

From the project root, run:

```bash
python scripts/select_env.py int
python scripts/select_env.py syst
python scripts/select_env.py accept
```

## Prompt strategy for retrieved chunks

Use a prompt-builder that injects the retrieved matches and source metadata into the model context before the final answer.

```python
from scripts.prompt_builder import build_context_prompt

prompt = build_context_prompt(
    query="When do refunds arrive?",
    chunks=[
        {
            'id': 7,
            'source': 'policy.md',
            'text': 'Refunds are processed within 30 days.',
            'metadata': {'section': 'refunds', 'document': 'policy'}
        }
    ],
    max_chunks=5,
    include_metadata=True,
)
```

This produces a structured prompt with:

- the user question
- retrieved evidence blocks
- source names and IDs
- optional metadata such as section, document, or classification

The model is then instructed to answer using only the provided chunks and cite the source when possible.

## Agent orchestrator

`AgentOrchestrator` interprets the request and chooses a path:

- Knowledge or policy questions use retrieved chunks only.
- Requests involving current, live, latest, lookup, search, or state changes select registered tools.
- Selected tools are called through the `MCPToolClient` adapter.
- Retrieved evidence and MCP results are combined into one synthesis prompt.

```python
from scripts.orchestrator import AgentOrchestrator, ToolSpec

agent = AgentOrchestrator(
    chunks=chunks,
    mcp_client=mcp_client,
    tools=[ToolSpec('order_status', 'check current order status')],
    synthesizer=llm_client.complete,
)

result = agent.run('What is the latest order status?')
print(result.answer)
print(result.operational_trace)
```

The MCP client only needs to expose `call_tool(name, arguments)`. This keeps the orchestration logic independent of a specific MCP SDK and makes it straightforward to connect an MCP server client.

### Local MCP server

The project includes one MCP-compatible local server using stdio and newline-delimited JSON-RPC messages:

```powershell
python scripts/mcp_server.py
```

It exposes `search_policy_documents`, `get_policy_section`, `retrieve_policy`, `lookup_employee_profile`, `check_pto_balance`, `lookup_benefits_status`, `check_policy_compliance`, `create_mock_hr_ticket`, `draft_hr_email`, `order_status`, `employee_record`, `create_hr_ticket`, and `update_case_record` through `initialize`, `tools/list`, and `tools/call`. A host process should start the server and exchange JSON-RPC messages through standard input and output.

The real agent-to-server path uses [scripts/mcp_client.py](scripts/mcp_client.py):

```python
from scripts.mcp_client import StdioMCPClient
from scripts.orchestrator import AgentOrchestrator, ToolSpec

mcp_client = StdioMCPClient()
agent = AgentOrchestrator(
    chunks=[],
    mcp_client=mcp_client,
    tools=[ToolSpec('retrieve_policy', 'retrieve HR policy evidence')],
    synthesizer=llm_client.complete,
)
result = agent.run('What does the PTO policy require?')
mcp_client.close()
```

The orchestrator invokes `StdioMCPClient.call_tool`, which sends an MCP JSON-RPC `tools/call` request to the server process. It does not call the server's handler functions directly.

### MCP architecture and transport

The integration uses a local MCP server process connected through **stdio**. The client starts `scripts/mcp_server.py`, writes newline-delimited JSON-RPC messages to the server's standard input, and reads responses from standard output. This keeps the transport local and lightweight without requiring an HTTP service or external network listener.

The request lifecycle is:

1. `StdioMCPClient` starts the server process.
2. The client sends `initialize` and receives the server capabilities and identity.
3. The client sends `tools/list` to discover available tool names, descriptions, and input schemas.
4. The agent selects a discovered tool based on user intent and required inputs.
5. The client sends `tools/call` with the selected tool name and validated arguments.
6. The server returns `structuredContent` and text content, or a JSON-RPC error.
7. The orchestrator adds the tool result to the synthesis context and operational trace.

The server handles `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, and `ping`. The client never imports or invokes the server's tool handlers directly.

### Tool schemas

Each tool is advertised with an MCP schema containing `name`, `description`, and JSON Schema-compatible `inputSchema`. Representative schemas are:

```json
{
    "name": "retrieve_policy",
    "description": "Retrieve relevant HR policy evidence from the local RAG index.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 10}
        },
        "required": ["query"]
    }
}
```

```json
{
    "name": "lookup_employee_profile",
    "inputSchema": {
        "type": "object",
        "properties": {"employee_id": {"type": "string"}},
        "required": ["employee_id"]
    }
}
```

Policy tools validate query inputs and return source metadata. Employee and benefits tools require `employee_id`. Mutating tools additionally accept `confirmed`, but the server executes them only when it is explicitly `true`; otherwise it returns a mock `confirmation_required` result.

### Discovery and invocation example

Tool discovery is performed through the MCP client:

```python
mcp_client = StdioMCPClient()
available_tools = mcp_client.list_tools()

policy_result = mcp_client.call_tool(
        'retrieve_policy',
        {'query': 'remote work eligibility', 'top_k': 3},
)
```

The orchestrator normally performs this call indirectly after intent routing. Tool failures, missing arguments, and unavailable servers are returned as controlled errors and recorded in the operational trace.

`search_policy_documents`, `get_policy_section`, and `retrieve_policy` use the local RAG index and return structured policy results containing IDs, source names, text, and metadata. `lookup_employee_profile`, `check_pto_balance`, and `lookup_benefits_status` return mock structured HR data. `create_mock_hr_ticket` and `draft_hr_email` support mock operations until explicit confirmation is provided. `check_policy_compliance` returns a mock compliance assessment and should be verified against current policy evidence.

Mutating tools return a mock confirmation result unless their arguments contain `confirmed: true`. This server-side check complements the orchestrator confirmation gate.

### Confirmation safety

Mutating or externally consequential actions are never executed by default. Tools that create HR tickets, draft or send manager messages, update case records, submit requests, approve changes, or delete data return a mock result with `status=confirmation_required`.

```python
# Safe preview: no mutating MCP call is made.
preview = agent.run('Create an HR ticket for my leave issue')

# Execute only after the user explicitly confirms the exact action.
confirmed = agent.run(
    'Create an HR ticket for my leave issue',
    confirmed=True,
)
```

Tool definitions can also force confirmation explicitly with `ToolSpec(..., requires_confirmation=True)`. Confirmation must be obtained outside the model and passed by the trusted application layer.

### Operational trace

Each result includes a concise `operational_trace` with architectural events, without exposing hidden chain-of-thought:

- `intent`: routing decision, selected tools, and workflow
- `retrieval`: top-k count and retrieved policy source IDs/names
- `tool_call`: selected MCP tool and arguments
- `tool_result`: returned tool output
- `synthesis`: final answer basis and escalation decision

For centralized logging, pass a callback as `trace_sink`:

```python
agent = AgentOrchestrator(
    chunks=chunks,
    trace_sink=lambda event: logger.info('agent_trace=%s', event),
)
```

Escalation is marked when no policy sources or tool results are available, or when a required tool did not produce a result.

### Failure handling

The orchestrator keeps failures in the normal response flow:

- Unavailable or failing MCP clients produce a `tool_error` trace and an escalation recommendation.
- Required arguments such as `employee_id` are validated before a tool call; missing values are reported without calling the tool.
- Unregistered tools are recorded as unavailable instead of crashing the request.
- Empty or ambiguous requests return a focused clarification question.
- Incomplete policy evidence is surfaced as an escalation reason rather than presented as a confident answer.

## HR workflows

The orchestrator supports two multi-step HR workflows:

### Remote-work eligibility

The workflow guides the user through role and location, policy eligibility, manager approval and team coverage, security readiness, and the final eligibility decision.

### PTO request guidance

The workflow guides the user through PTO dates and type, balance and policy checks, handover planning, approval routing, submission channel, and confirmation.

Both workflows validate required fields before advancing and include the active workflow steps in the LLM synthesis prompt. HR policy chunks should be supplied as retrieved context; approval or employee-record checks can be exposed as MCP tools.

## Optional wrapper commands

```bash
python -m pytest
python tests/test_retrieval.py
python tests/test_prompt_builder.py
python tests/test_orchestrator.py
python tests/test_hr_workflows.py
python tests/test_mcp_server.py
```

## Python setup

Install Python 3.11 or newer and enable the option to add Python to `PATH` during installation. Then install the project dependencies:

```powershell
python -m pip install -r requirements.txt
```

If `python` is not recognized on Windows, open a new PowerShell window after installing Python, or use the Python launcher:

```powershell
py -m pip install -r requirements.txt
py -m unittest discover -s tests
```

After Python is available, run the complete test suite with:

```powershell
python -m unittest discover -s tests
```

The current `.env` file is updated when an environment is selected.
