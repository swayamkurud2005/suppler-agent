// ============================================================
// DOCUMENTS SERVICE
// Connected to FastAPI: POST /api/documents/upload, GET /api/documents
// ============================================================

import { apiUpload, apiGet } from './client';

export async function uploadContractDocument(file, supplierId = 'SUP-001') {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('supplier_id', supplierId);

  const res = await apiUpload('/documents/upload', formData);
  if (res && res.status === 'success') {
    return res;
  }

  return res || { status: 'error', message: 'Contract upload failed' };
}

export async function getDocuments() {
  const res = await apiGet('/documents');
  if (res && res.status === 'success' && Array.isArray(res.data)) {
    return res;
  }

  return res || { status: 'error', data: [], message: 'Unable to load documents' };
}
