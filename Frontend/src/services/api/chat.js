// ============================================================
// CHAT SERVICE — persistent chat sessions & message history
// Connected to FastAPI: /api/chat/*
// ============================================================

import { apiGet, apiPost, apiClient } from './client';

/**
 * List all chat sessions (optionally filtered by supplierId)
 */
export async function getChatSessions(supplierId = null) {
  const params = {};
  if (supplierId) params.supplier_id = supplierId;
  return apiGet('/chat/sessions', params);
}

/**
 * Create a new chat session
 */
export async function createChatSession(supplierId = null, supplierName = null, title = null) {
  return apiPost('/chat/sessions', {
    supplier_id: supplierId,
    supplier_name: supplierName,
    title: title || 'New Chat',
  });
}

/**
 * Load all messages in a session
 */
export async function getSessionMessages(sessionId) {
  return apiGet(`/chat/sessions/${sessionId}/messages`);
}

/**
 * Send a message in a session and get AI response
 */
export async function sendSessionMessage(sessionId, message, supplierId = null) {
  return apiPost(`/chat/sessions/${sessionId}/messages`, {
    message,
    supplier_id: supplierId,
  });
}

/**
 * Rename a chat session
 */
export async function renameChatSession(sessionId, title) {
  return apiClient(`/chat/sessions/${sessionId}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  });
}

/**
 * Delete a chat session
 */
export async function deleteChatSession(sessionId) {
  return apiClient(`/chat/sessions/${sessionId}`, {
    method: 'DELETE',
  });
}
