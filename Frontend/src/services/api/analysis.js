import { apiPost } from './client';

export async function runAnalysis(supplierId, analysisType) {
  const res = await apiPost(`/analysis/${analysisType}`, { supplierId, analysisType });
  return res || { status: 'error', message: 'Analysis service is unavailable' };
}
