// ============================================================
// ASSISTANT SERVICE
// Connected to FastAPI: POST /api/analysis/assistant/query
// ============================================================

import { apiPost } from './client';

export async function sendAssistantMessage(supplierId, message) {
  // Call AI Assistant agent endpoint
  const res = await apiPost('/analysis/assistant/query', {
    supplierId,
    message,
  });

  if (res && res.status === 'success' && res.data) {
    return res;
  }

  return res || { status: 'error', message: 'AI assistant is unavailable' };
}
