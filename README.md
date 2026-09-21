# Environment selector project

This project includes separate environment files for:

- int
- syst
- accept

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
