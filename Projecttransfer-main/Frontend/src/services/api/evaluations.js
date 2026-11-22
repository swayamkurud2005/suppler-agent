import { API_BASE_URL } from './client';

async function request(endpoint, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${endpoint}`, {
      ...options,
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    });
  } catch {
    throw new Error('The evaluation API is unreachable. Check that the backend is running.');
  }

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `Evaluation API returned ${response.status}.`);
  }
  return payload;
}

export async function listEvaluationRuns() {
  const payload = await request('/evaluations/runs');
  return payload.data || [];
}

export async function getEvaluationRun(runId) {
  const payload = await request(`/evaluations/runs/${encodeURIComponent(runId)}`);
  return payload.data;
}

export async function getEvaluationRecords(runId) {
  const payload = await request(`/evaluations/runs/${encodeURIComponent(runId)}/records`);
  return payload.data || [];
}

export async function startEvaluationRun({ limit, allowExternalCalls }) {
  return request('/evaluations/runs', {
    method: 'POST',
    body: JSON.stringify({ limit, allow_external_calls: allowExternalCalls }),
  });
}
