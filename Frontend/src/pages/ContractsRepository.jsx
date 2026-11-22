import { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  FileText,
  Download,
  Search,
  Filter,
  Calendar,
  Building2,
  CloudOff,
  Cloud,
  RefreshCw,
  ArrowUpDown,
  ChevronDown,
  ExternalLink,
  AlertCircle,
} from 'lucide-react';
import { getAllContracts, downloadContract } from '../services';

const STATUS_COLORS = {
  active: 'badge-success',
  expired: 'badge-danger',
  pending: 'badge-warning',
  terminated: 'badge-danger',
  draft: 'badge-info',
};

export default function ContractsRepository() {
  const [contracts, setContracts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sortField, setSortField] = useState('createdAt');
  const [sortDir, setSortDir] = useState('desc');
  const [downloadingId, setDownloadingId] = useState(null);

  useEffect(() => {
    loadContracts();
  }, []);

  async function loadContracts() {
    setLoading(true);
    setError(null);
    try {
      const res = await getAllContracts();
      if (res?.status === 'success' && Array.isArray(res.data)) {
        setContracts(res.data);
      } else {
        setContracts([]);
      }
    } catch (err) {
      console.error('Failed to load contracts', err);
      setError('Failed to load contracts. Please check that the backend is running.');
    } finally {
      setLoading(false);
    }
  }

  async function handleDownload(contract) {
    setDownloadingId(contract.id);
    try {
      await downloadContract(contract.id, contract.documents?.[0]?.name);
    } catch (err) {
      console.error('Download failed', err);
      alert('Failed to download contract. The file may not be available.');
    } finally {
      setDownloadingId(null);
    }
  }

  // Filtering and sorting
  const filteredContracts = useMemo(() => {
    let filtered = [...contracts];

    // Search filter
    if (searchTerm.trim()) {
      const q = searchTerm.toLowerCase();
      filtered = filtered.filter(
        (c) =>
          (c.supplierName || '').toLowerCase().includes(q) ||
          (c.contractTitle || '').toLowerCase().includes(q) ||
          (c.id || '').toLowerCase().includes(q) ||
          (c.contractType || '').toLowerCase().includes(q) ||
          (c.governingLaw || '').toLowerCase().includes(q)
      );
    }

    // Status filter
    if (statusFilter !== 'all') {
      filtered = filtered.filter((c) => (c.status || '').toLowerCase() === statusFilter);
    }

    // Sort
    filtered.sort((a, b) => {
      let aVal = a[sortField] || '';
      let bVal = b[sortField] || '';
      if (typeof aVal === 'string') aVal = aVal.toLowerCase();
      if (typeof bVal === 'string') bVal = bVal.toLowerCase();
      if (aVal < bVal) return sortDir === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });

    return filtered;
  }, [contracts, searchTerm, statusFilter, sortField, sortDir]);

  function toggleSort(field) {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  }

  const uniqueStatuses = useMemo(() => {
    const s = new Set(contracts.map((c) => (c.status || 'active').toLowerCase()));
    return Array.from(s);
  }, [contracts]);

  function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
      return new Date(dateStr).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });
    } catch {
      return dateStr;
    }
  }

  return (
    <div className="animate-fade-in">
      {/* Page Header */}
      <div className="page-header flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="page-title">Contracts Repository</h1>
          <p className="page-subtitle">
            Browse, search, and download all supplier contracts stored in the cloud database.
          </p>
        </div>
        <div className="flex gap-2 self-start md:self-auto">
          <button onClick={loadContracts} className="btn btn-secondary flex items-center gap-2" disabled={loading}>
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
          <Link to="/suppliers" className="btn btn-primary flex items-center gap-2">
            <FileText size={16} />
            Add New Supplier
          </Link>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <div className="card">
          <div className="card-body flex items-center gap-4">
            <div className="p-3 rounded-lg bg-blue-50">
              <FileText size={24} className="text-blue-600" />
            </div>
            <div>
              <div className="text-2xl font-bold text-gray-900">{contracts.length}</div>
              <div className="text-sm text-gray-500">Total Contracts</div>
            </div>
          </div>
        </div>
        <div className="card">
          <div className="card-body flex items-center gap-4">
            <div className="p-3 rounded-lg bg-emerald-50">
              <Building2 size={24} className="text-emerald-600" />
            </div>
            <div>
              <div className="text-2xl font-bold text-gray-900">
                {new Set(contracts.map((c) => c.supplierId).filter(Boolean)).size}
              </div>
              <div className="text-sm text-gray-500">Suppliers</div>
            </div>
          </div>
        </div>
        <div className="card">
          <div className="card-body flex items-center gap-4">
            <div className="p-3 rounded-lg bg-purple-50">
              <Cloud size={24} className="text-purple-600" />
            </div>
            <div>
              <div className="text-2xl font-bold text-gray-900">
                {contracts.filter((c) => c.hasDownload).length}
              </div>
              <div className="text-sm text-gray-500">Downloadable</div>
            </div>
          </div>
        </div>
        <div className="card">
          <div className="card-body flex items-center gap-4">
            <div className="p-3 rounded-lg bg-amber-50">
              <Calendar size={24} className="text-amber-600" />
            </div>
            <div>
              <div className="text-2xl font-bold text-gray-900">
                {contracts.filter((c) => (c.status || '').toLowerCase() === 'active').length}
              </div>
              <div className="text-sm text-gray-500">Active Contracts</div>
            </div>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="card mb-6">
        <div className="card-body flex flex-col sm:flex-row gap-3 items-stretch sm:items-center">
          <div className="relative flex-1">
            <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="Search by supplier, contract title, ID, or type..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          <div className="flex items-center gap-2">
            <Filter size={16} className="text-gray-500" />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-3 py-2.5 border border-gray-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">All Statuses</option>
              {uniqueStatuses.map((s) => (
                <option key={s} value={s}>
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="card mb-6">
          <div className="card-body flex items-center gap-3 text-red-700 bg-red-50 rounded-lg p-4">
            <AlertCircle size={20} />
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Contracts Table */}
      <div className="card">
        <div className="card-header flex justify-between items-center">
          <h2 className="card-title">
            All Contracts
            {filteredContracts.length !== contracts.length && (
              <span className="text-sm font-normal text-gray-500 ml-2">
                ({filteredContracts.length} of {contracts.length})
              </span>
            )}
          </h2>
          <span className="badge badge-info">{contracts.length} Total</span>
        </div>
        <div className="card-body p-0">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <RefreshCw size={28} className="animate-spin text-blue-500 mr-3" />
              <span className="text-gray-500 text-lg">Loading contracts...</span>
            </div>
          ) : filteredContracts.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-gray-500">
              <FileText size={48} className="mb-4 text-gray-300" />
              <p className="text-lg font-medium">No contracts found</p>
              <p className="text-sm mt-1">
                {searchTerm || statusFilter !== 'all'
                  ? 'Try adjusting your search or filters.'
                  : 'Upload a contract through the Documents or Add Supplier page.'}
              </p>
            </div>
          ) : (
            <div className="table-container">
              <table className="table">
                <thead>
                  <tr>
                    <th className="cursor-pointer select-none" onClick={() => toggleSort('id')}>
                      <span className="flex items-center gap-1">
                        Contract ID <ArrowUpDown size={14} />
                      </span>
                    </th>
                    <th className="cursor-pointer select-none" onClick={() => toggleSort('supplierName')}>
                      <span className="flex items-center gap-1">
                        Supplier <ArrowUpDown size={14} />
                      </span>
                    </th>
                    <th className="cursor-pointer select-none" onClick={() => toggleSort('contractTitle')}>
                      <span className="flex items-center gap-1">
                        Title <ArrowUpDown size={14} />
                      </span>
                    </th>
                    <th>Type</th>
                    <th className="cursor-pointer select-none" onClick={() => toggleSort('status')}>
                      <span className="flex items-center gap-1">
                        Status <ArrowUpDown size={14} />
                      </span>
                    </th>
                    <th>Effective</th>
                    <th>Expiry</th>
                    <th>Storage</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredContracts.map((c) => {
                    const doc = c.documents?.[0];
                    const hasCloud = doc?.hasCloudCopy;
                    return (
                      <tr key={c.id}>
                        <td>
                          <span className="badge badge-info font-mono text-xs">{c.id}</span>
                        </td>
                        <td>
                          <Link
                            to={`/suppliers/${c.supplierId}/overview`}
                            className="text-blue-600 hover:text-blue-800 hover:underline font-medium flex items-center gap-1"
                          >
                            {c.supplierName || 'Unknown'}
                            <ExternalLink size={12} className="opacity-50" />
                          </Link>
                          {c.supplierCategory && (
                            <div className="text-xs text-gray-400 mt-0.5">{c.supplierCategory}</div>
                          )}
                        </td>
                        <td>
                          <div className="font-medium text-gray-800 max-w-[220px] truncate" title={c.contractTitle || '—'}>
                            {c.contractTitle || '—'}
                          </div>
                        </td>
                        <td className="text-sm text-gray-600">{c.contractType || '—'}</td>
                        <td>
                          <span className={`badge ${STATUS_COLORS[c.status?.toLowerCase()] || 'badge-info'}`}>
                            {c.status || 'active'}
                          </span>
                        </td>
                        <td className="text-sm text-gray-600 whitespace-nowrap">{formatDate(c.startDate)}</td>
                        <td className="text-sm text-gray-600 whitespace-nowrap">{formatDate(c.expiryDate)}</td>
                        <td>
                          {c.hasDownload ? (
                            <span
                              className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-emerald-50 text-emerald-700"
                              title={hasCloud ? 'Stored in cloud database' : 'Stored on local disk'}
                            >
                              {hasCloud ? <Cloud size={12} /> : <CloudOff size={12} />}
                              {hasCloud ? 'Cloud' : 'Local'}
                            </span>
                          ) : (
                            <span className="text-xs text-gray-400">—</span>
                          )}
                        </td>
                        <td>
                          <div className="flex items-center gap-2">
                            {c.hasDownload ? (
                              <button
                                onClick={() => handleDownload(c)}
                                disabled={downloadingId === c.id}
                                className="btn btn-primary py-1.5 px-3 text-xs flex items-center gap-1.5"
                                title={`Download ${doc?.name || 'contract'}`}
                              >
                                {downloadingId === c.id ? (
                                  <RefreshCw size={14} className="animate-spin" />
                                ) : (
                                  <Download size={14} />
                                )}
                                {downloadingId === c.id ? 'Downloading...' : 'Download'}
                              </button>
                            ) : (
                              <span className="text-xs text-gray-400 italic">No file</span>
                            )}
                            <Link
                              to={`/suppliers/${c.supplierId}/contract`}
                              className="btn btn-secondary py-1.5 px-3 text-xs flex items-center gap-1.5"
                              title="View contract details"
                            >
                              <FileText size={14} />
                              View
                            </Link>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Footer info */}
      <div className="mt-4 text-sm text-gray-500 bg-blue-50 p-4 rounded-md border border-blue-100 flex gap-3">
        <Cloud className="text-blue-500 flex-shrink-0" size={20} />
        <p>
          <strong>Cloud Storage:</strong> Contract documents uploaded during supplier onboarding are
          stored in the Neon PostgreSQL cloud database. Downloads are served directly from the cloud,
          making them accessible from anywhere.
        </p>
      </div>
    </div>
  );
}
