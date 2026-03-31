const API_BASE = '/api';

export async function sendMessage(message, model = null, options = {}) {
  const body = { 
    message,
    ...options
  };
  
  if (model !== null) {
    body.model = model;
  }
  
  if (options.temperature !== undefined) {
    body.temperature = options.temperature;
  }
  
  if (options.max_tokens !== undefined) {
    body.max_tokens = options.max_tokens;
  }
  
  if (options.top_p !== undefined) {
    body.top_p = options.top_p;
  }
  
  if (options.strictMode !== undefined) {
    body.strictMode = options.strictMode;
  }
  
  if (options.conversationId !== undefined) {
    body.conversationId = options.conversationId;
  }
  
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to send message');
  }
  
  return response.json();
}

export async function submitCorrection(conversationId, userCorrection, userMessage, agentResponse) {
  const response = await fetch(`${API_BASE}/correct`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      conversationId,
      userCorrection,
      userMessage,
      agentResponse
    })
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to submit correction');
  }
  
  return response.json();
}

export async function getConversations() {
  const response = await fetch(`${API_BASE}/conversations`);
  if (!response.ok) throw new Error('Failed to get conversations');
  return response.json();
}

export async function getCorrections() {
  const response = await fetch(`${API_BASE}/corrections`);
  if (!response.ok) throw new Error('Failed to get corrections');
  return response.json();
}

export async function getLearnings() {
  const response = await fetch(`${API_BASE}/learnings`);
  if (!response.ok) throw new Error('Failed to get learnings');
  return response.json();
}

export async function resetMemory() {
  const response = await fetch(`${API_BASE}/reset`, { method: 'DELETE' });
  if (!response.ok) throw new Error('Failed to reset memory');
  return response.json();
}

export async function checkHealth() {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) throw new Error('Failed to check health');
  return response.json();
}

export async function getTokenUsage() {
  const response = await fetch(`${API_BASE}/tokens`);
  if (!response.ok) throw new Error('Failed to get token usage');
  return response.json();
}

export async function getTokenUsageBySession(sessionId = null) {
  const url = sessionId 
    ? `${API_BASE}/tokens/session/${sessionId}`
    : `${API_BASE}/tokens/session`;
  const response = await fetch(url);
  if (!response.ok) throw new Error('Failed to get session token usage');
  return response.json();
}

export async function getTokenUsageByModel() {
  const response = await fetch(`${API_BASE}/tokens/models`);
  if (!response.ok) throw new Error('Failed to get model token usage');
  return response.json();
}

export async function getDailyTokenUsage(days = 7) {
  const response = await fetch(`${API_BASE}/tokens/daily?days=${days}`);
  if (!response.ok) throw new Error('Failed to get daily token usage');
  return response.json();
}

export async function getSessionStats() {
  const response = await fetch(`${API_BASE}/tokens/sessions`);
  if (!response.ok) throw new Error('Failed to get session stats');
  return response.json();
}

export async function resetTokenUsage() {
  const response = await fetch(`${API_BASE}/tokens/reset`, { method: 'POST' });
  if (!response.ok) throw new Error('Failed to reset token usage');
  return response.json();
}

export async function createNewSession() {
  const response = await fetch(`${API_BASE}/session/new`, { method: 'POST' });
  if (!response.ok) throw new Error('Failed to create new session');
  return response.json();
}

export async function getAvailableModels() {
  const response = await fetch(`${API_BASE}/models`);
  if (!response.ok) throw new Error('Failed to get models');
  return response.json();
}
