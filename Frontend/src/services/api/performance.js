// ============================================================
// PERFORMANCE SERVICE
// Connected to FastAPI: GET /api/performance/suppliers/{id}/performance
// ============================================================

import { apiGet } from './client';

export async function getPerformanceBySupplier(supplierId) {
  const res = await apiGet(`/performance/suppliers/${supplierId}/performance`);
  if (res && res.status === 'success' && res.data) {
    return res;
  }

  return res || { status: 'error', data: null, message: 'No performance data found' };
}

export async function getAllPerformance() {
  const res = await apiGet('/performance');
  if (res && res.status === 'success' && Array.isArray(res.data)) {
    return res;
  }

  return res || { status: 'error', data: [], message: 'Unable to load performance' };
}
