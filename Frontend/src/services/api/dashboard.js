// ============================================================
// DASHBOARD SERVICE
// Connected to FastAPI: GET /api/dashboard/metrics, GET /api/dashboard/charts
// Validates response shapes and provides clean fallbacks
// ============================================================

import { apiGet } from './client';

export async function getDashboardMetrics() {
  const res = await apiGet('/dashboard/metrics');
  if (res && res.status === 'success' && res.data) {
    return res;
  }

  return res || { status: 'error', data: null, message: 'Unable to load dashboard metrics' };
}

export async function getDashboardCharts() {
  const res = await apiGet('/dashboard/charts');
  if (res && res.status === 'success' && res.data) {
    return res;
  }

  return res || { status: 'error', data: null, message: 'Unable to load dashboard charts' };
}
