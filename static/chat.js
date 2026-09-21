const form = document.querySelector('#chat-form');
const input = document.querySelector('#message-input');
const chatLog = document.querySelector('#chat-log');
const sendButton = document.querySelector('#send-button');
const sources = document.querySelector('#sources');
const trace = document.querySelector('#trace');
const traceCount = document.querySelector('#trace-count');
const connectionStatus = document.querySelector('#connection-status');
const confirmationPanel = document.querySelector('#confirmation-panel');
const confirmButton = document.querySelector('#confirm-action');
let pendingMessage = null;

function addMessage(role, text) {
  const article = document.createElement('article');
  article.className = `message ${role}-message`;
  const avatar = role === 'assistant' ? 'PD' : 'YOU';
  article.innerHTML = `<div class="avatar">${avatar}</div><div class="message-body"><p class="message-label">${role === 'assistant' ? 'People Desk' : 'You'}</p><p></p></div>`;
  article.querySelector('p:last-child').textContent = text;
  chatLog.appendChild(article);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function renderEvidence(data) {
  sources.innerHTML = '';
  if (!data.sources?.length) {
    sources.innerHTML = '<p class="empty-state">No policy sources retrieved.</p>';
  } else {
    data.sources.forEach((item) => {
      const node = document.createElement('div');
      node.className = 'source-item';
      node.innerHTML = `<strong></strong><span></span>`;
      node.querySelector('strong').textContent = item.source || 'Unknown source';
      node.querySelector('span').textContent = `Chunk ${item.id ?? 'unlisted'}`;
      sources.appendChild(node);
    });
  }

  trace.innerHTML = '';
  (data.trace || []).forEach((event) => {
    const node = document.createElement('div');
    node.className = 'trace-item';
    node.textContent = `${event.event}: ${JSON.stringify(event)}`;
    trace.appendChild(node);
  });
  traceCount.textContent = String(data.trace?.length || 0);
}

async function sendMessage(message, confirmed = false) {
  if (!message) return;
  addMessage('user', message);
  sendButton.disabled = true;
  sendButton.textContent = '...';
  confirmationPanel.classList.add('hidden');
  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message, confirmed}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'The assistant could not respond.');
    addMessage('assistant', data.answer);
    renderEvidence(data);
    if (data.confirmation_required) {
      pendingMessage = message;
      confirmationPanel.classList.remove('hidden');
    }
  } catch (error) {
    addMessage('assistant', error.message);
  } finally {
    sendButton.disabled = false;
    sendButton.innerHTML = 'Send <span>↗</span>';
    input.focus();
  }
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const message = input.value.trim();
  input.value = '';
  sendMessage(message);
});

document.querySelectorAll('.starter').forEach((button) => {
  button.addEventListener('click', () => {
    input.value = button.dataset.prompt;
    input.focus();
  });
});

confirmButton.addEventListener('click', () => {
  if (pendingMessage) sendMessage(pendingMessage, true);
});

document.querySelectorAll('.demo-button').forEach((button) => {
  button.addEventListener('click', async () => {
    const taskId = button.dataset.demo;
    button.disabled = true;
    try {
      const response = await fetch(`/api/demo/${taskId}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({confirmed: false}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Demo task failed.');
      addMessage('user', `Demo: ${taskId}`);
      addMessage('assistant', data.answer);
      renderEvidence(data);
    } catch (error) {
      addMessage('assistant', error.message);
    } finally {
      button.disabled = false;
    }
  });
});

input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

fetch('/api/health').then((response) => response.json()).then((data) => {
  connectionStatus.textContent = data.mcp_connected ? 'MCP tools connected' : 'RAG mode · MCP unavailable';
}).catch(() => {
  connectionStatus.textContent = 'Assistant connection unavailable';
});
