// ============================================================
// MARKET PRICING BENCHMARKING SERVICE
// Connected to FastAPI: /api/suppliers/{id}/pricing/*
// ============================================================

import { apiGet, apiPost } from './client';

export async function getPricingAnalysis(supplierId) {
  const res = await apiGet(`/suppliers/${supplierId}/pricing/analysis`);
  return res || { status: 'error', message: 'Failed to retrieve pricing analysis' };
}

export async function runPricingResearch(supplierId, params = {}) {
  const res = await apiPost(`/suppliers/${supplierId}/pricing/research`, params);
  return res || { status: 'error', message: 'Pricing research failed' };
}

export async function refreshPricingResearch(supplierId, params = {}) {
  const res = await apiPost(`/suppliers/${supplierId}/pricing/refresh`, params);
  return res || { status: 'error', message: 'Failed to refresh pricing research' };
}

export async function getPricingSources(supplierId) {
  const res = await apiGet(`/suppliers/${supplierId}/pricing/sources`);
  return res || { status: 'error', message: 'Failed to fetch pricing sources' };
}
