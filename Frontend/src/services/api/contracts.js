// ============================================================
// CONTRACTS SERVICE
// Connected to FastAPI: GET /api/contracts, GET /api/contracts/suppliers/{id}/contract
// ============================================================

import { apiGet, simulateDelay, API_BASE_URL } from './client';
import { mockContracts } from '../../data/mockData';

export async function getContractBySupplier(supplierId) {
  const res = await apiGet(`/contracts/suppliers/${supplierId}/contract`);
  if (res && res.status === 'success' && res.data) {
    return res;
  }

  await simulateDelay(200);
  const contract = mockContracts.find((c) => c.supplierId === supplierId);
  if (!contract) {
    return { status: 'error', data: null, message: 'No contract found' };
  }
  return { status: 'success', data: contract };
}

export async function getAllContracts() {
  const res = await apiGet('/contracts');
  if (res && res.status === 'success' && Array.isArray(res.data) && res.data.length > 0) {
    return res;
  }

  await simulateDelay(200);
  return { status: 'success', data: mockContracts };
}

/**
 * Download a contract document by streaming it as a blob and triggering
 * the browser's native download dialog.
 */
export async function downloadContract(contractId, filename) {
  const url = `${API_BASE_URL}/contracts/${contractId}/download`;
  const res = await fetch(url);
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new Error(errBody.detail || `Download failed (HTTP ${res.status})`);
  }
  const blob = await res.blob();
  const blobUrl = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = blobUrl;
  a.download = filename || `contract-${contractId}.pdf`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(blobUrl);
}
