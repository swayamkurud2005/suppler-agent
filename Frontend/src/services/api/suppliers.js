// ============================================================
// SUPPLIERS SERVICE
// Connected to FastAPI: GET /api/suppliers, GET /api/suppliers/{id}, POST /api/suppliers
// ============================================================

import { apiGet, apiPost, apiDelete, apiUpload } from './client';

export async function getSuppliers(filters = {}) {
  const res = await apiGet('/suppliers', filters);
  if (res && res.status === 'success' && Array.isArray(res.data)) {
    return res;
  }
  return res || { status: 'error', data: [], message: 'Unable to load suppliers' };
}

export async function createSupplier(supplierData) {
  const res = await apiPost('/suppliers', supplierData);
  if (res && res.status === 'success' && res.data) {
    return res;
  }

  return res || { status: 'error', message: res?.message || 'Unable to create supplier' };
}

export async function extractSupplierFromContract(file) {
  const formData = new FormData();
  formData.append('file', file);

  const res = await apiUpload('/suppliers/extract-from-contract', formData);
  if (res && res.status === 'success' && res.data) {
    return res;
  }

  return res || { status: 'error', message: res?.message || 'Contract extraction failed' };
}

export async function getAvailableDocuments() {
  const res = await apiGet('/suppliers/available-documents');
  if (res && res.status === 'success' && Array.isArray(res.data)) {
    return res;
  }
  return res || { status: 'error', data: [], message: 'Unable to load available documents' };
}

export async function extractSupplierFromExisting(params = {}) {
  const res = await apiPost('/suppliers/extract-from-existing', params);
  if (res && res.status === 'success' && res.data) {
    return res;
  }
  return res || { status: 'error', message: res?.message || 'Extraction from existing document failed' };
}

export async function getSupplierById(supplierId) {
  const res = await apiGet(`/suppliers/${supplierId}`);
  if (res && res.status === 'success' && res.data) {
    return res;
  }

  return res || { status: 'error', data: null, message: 'Supplier not found' };
}

export async function getSupplierCategories() {
  const res = await apiGet('/suppliers/categories');
  if (res && res.status === 'success' && Array.isArray(res.data)) {
    return res;
  }

  return res || { status: 'error', data: [], message: 'Unable to load categories' };
}

export async function deleteSupplier(supplierId) { return apiDelete(`/suppliers/${supplierId}`); }
