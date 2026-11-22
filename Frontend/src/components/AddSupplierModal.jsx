import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  X,
  Upload,
  FileText,
  Sparkles,
  CheckCircle,
  AlertTriangle,
  Info,
  Edit3,
  RefreshCw,
  Trash2,
  Building2,
  ArrowRight,
  ShieldCheck,
  FileCheck,
  FolderOpen,
  Search,
} from 'lucide-react';
import { createSupplier, extractSupplierFromContract, getAvailableDocuments, extractSupplierFromExisting } from '../services';

const DEFAULT_CATEGORIES = [
  'Raw Materials',
  'Electronics & Semiconductors',
  'Precision Machining',
  'Hydraulics & Fluid Power',
  'Packaging & Logistics',
  'Fasteners & Hardware',
  'Other / General',
];

export default function AddSupplierModal({ isOpen, onClose, onSupplierCreated, categories = [] }) {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);

  const availableCategories = categories.length > 0 ? categories : DEFAULT_CATEGORIES;

  // File Upload State
  const [inputMode, setInputMode] = useState('upload'); // 'upload' | 'existing'
  const [availableDocs, setAvailableDocs] = useState([]);
  const [selectedExistingDoc, setSelectedExistingDoc] = useState(null);
  const [docFilter, setDocFilter] = useState('');
  const [docsLoading, setDocsLoading] = useState(false);

  const [selectedFile, setSelectedFile] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isExtracting, setIsExtracting] = useState(false);
  const [extractionProgress, setExtractionProgress] = useState(0);
  const [extractionStatusText, setExtractionStatusText] = useState('');
  const [extractionError, setExtractionError] = useState('');
  const [extractedMeta, setExtractedMeta] = useState(null);
  const [documentToken, setDocumentToken] = useState(null);
  const [uploadedFileName, setUploadedFileName] = useState(null);

  // Load available documents when modal opens
  useEffect(() => {
    if (isOpen) {
      loadDocs();
    }
  }, [isOpen]);

  const loadDocs = async () => {
    setDocsLoading(true);
    try {
      const res = await getAvailableDocuments();
      if (res && res.status === 'success' && Array.isArray(res.data)) {
        setAvailableDocs(res.data);
      }
    } catch (err) {
      console.error('Failed to load available documents:', err);
    } finally {
      setDocsLoading(false);
    }
  };

  // Form Data State
  const [formData, setFormData] = useState({
    name: '',
    category: availableCategories[0] || 'Raw Materials',
    location: '',
    contactPerson: '',
    contactEmail: '',
    contactPhone: '',
    status: 'active',
    relationshipYears: 1,
    riskScore: 25,
  });

  // Track which fields have been edited by the user after extraction
  const [editedFields, setEditedFields] = useState(new Set());
  // Active field for evidence popover
  const [activeEvidenceField, setActiveEvidenceField] = useState(null);

  // Submission State
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [createdSupplier, setCreatedSupplier] = useState(null);

  if (!isOpen) return null;

  // Format file size
  const formatFileSize = (bytes) => {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  };

  // Drag and drop handlers
  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileInputChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      validateAndSetFile(e.target.files[0]);
    }
  };

  const validateAndSetFile = (file) => {
    setExtractionError('');
    const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    if (!['.pdf', '.docx', '.doc', '.txt'].includes(ext)) {
      setExtractionError('Unsupported file type. Please upload a PDF or DOCX contract document.');
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      setExtractionError('File exceeds maximum 20 MB size limit.');
      return;
    }
    setSelectedFile(file);
  };

  const handleClearFile = () => {
    setSelectedFile(null);
    setSelectedExistingDoc(null);
    setExtractedMeta(null);
    setDocumentToken(null);
    setUploadedFileName(null);
    setExtractionError('');
    setExtractionProgress(0);
    setEditedFields(new Set());
    setActiveEvidenceField(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  // Trigger extraction from an existing / already-uploaded document
  const handleExtractExistingDetails = async () => {
    if (!selectedExistingDoc) return;

    setIsExtracting(true);
    setExtractionError('');
    setExtractionProgress(15);
    setExtractionStatusText('Reading existing contract document & clauses...');

    const progressTimer = setInterval(() => {
      setExtractionProgress((prev) => {
        if (prev < 45) {
          setExtractionStatusText('Retrieving contract clauses via hybrid RAG...');
          return prev + 15;
        }
        if (prev < 80) {
          setExtractionStatusText('Running AI extraction for verified supplier metadata...');
          return prev + 10;
        }
        return prev;
      });
    }, 450);

    try {
      const res = await extractSupplierFromExisting({
        document_name: selectedExistingDoc.filename,
        contract_id: selectedExistingDoc.contractId,
        supplier_id: selectedExistingDoc.supplierId,
      });
      clearInterval(progressTimer);
      setExtractionProgress(100);

      if (res && res.status === 'success' && res.data) {
        const data = res.data;
        setExtractedMeta(data);
        setDocumentToken(data.document_token);
        setUploadedFileName(data.filename);

        setFormData((prev) => ({
          ...prev,
          name: data.supplier_name?.value || prev.name,
          category: data.category?.value || prev.category,
          location: data.location?.value || prev.location,
          contactPerson: data.contact_person?.value || prev.contactPerson,
          contactEmail: data.contact_email?.value || prev.contactEmail,
          contactPhone: data.contact_phone?.value || prev.contactPhone,
        }));

        setEditedFields(new Set());
      } else {
        setExtractionError(res?.message || 'Failed to extract supplier details from document.');
      }
    } catch (err) {
      clearInterval(progressTimer);
      setExtractionError(err.message || 'Error occurred during contract extraction.');
    } finally {
      setIsExtracting(false);
    }
  };

  // Trigger contract extraction
  const handleExtractDetails = async () => {
    if (!selectedFile) return;

    setIsExtracting(true);
    setExtractionError('');
    setExtractionProgress(15);
    setExtractionStatusText('Parsing document structure & page segments...');

    const progressTimer = setInterval(() => {
      setExtractionProgress((prev) => {
        if (prev < 45) {
          setExtractionStatusText('Retrieving contract clauses via hybrid BM25...');
          return prev + 15;
        }
        if (prev < 80) {
          setExtractionStatusText('Running AI extraction for verified supplier metadata...');
          return prev + 10;
        }
        return prev;
      });
    }, 450);

    try {
      const res = await extractSupplierFromContract(selectedFile);
      clearInterval(progressTimer);
      setExtractionProgress(100);

      if (res && res.status === 'success' && res.data) {
        const data = res.data;
        setExtractedMeta(data);
        setDocumentToken(data.document_token);
        setUploadedFileName(data.filename);

        // Populate form data with extracted values
        setFormData((prev) => ({
          ...prev,
          name: data.supplier_name?.value || prev.name,
          category: data.category?.value || prev.category,
          location: data.location?.value || prev.location,
          contactPerson: data.contact_person?.value || prev.contactPerson,
          contactEmail: data.contact_email?.value || prev.contactEmail,
          contactPhone: data.contact_phone?.value || prev.contactPhone,
          // Relationship status is retained from user selection as per requirements
        }));

        // Reset edited fields tracking
        setEditedFields(new Set());
      } else {
        setExtractionError(res?.message || 'Failed to extract supplier details from contract.');
      }
    } catch (err) {
      clearInterval(progressTimer);
      setExtractionError(err.message || 'Error occurred during contract extraction.');
    } finally {
      setIsExtracting(false);
    }
  };

  // Form field change handler
  const handleFormChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
    // Mark this field as user-edited if it had an extracted value
    if (extractedMeta) {
      setEditedFields((prev) => new Set(prev).add(name));
    }
  };

  // Select an alternative candidate entity
  const handleSelectCandidate = (candidate) => {
    setFormData((prev) => ({ ...prev, name: candidate.name }));
    setEditedFields((prev) => new Set(prev).add('name'));
  };

  // Form submit handler
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!formData.name.trim()) {
      setSubmitError('Supplier / Company Name is required.');
      return;
    }

    setIsSubmitting(true);
    setSubmitError('');

    try {
      const payload = {
        name: formData.name.trim(),
        category: formData.category,
        location: formData.location.trim() || 'India',
        contactPerson: formData.contactPerson.trim() || null,
        contactEmail: formData.contactEmail.trim() || null,
        contactPhone: formData.contactPhone.trim() || null,
        status: formData.status,
        relationshipYears: Number(formData.relationshipYears) || 1,
        riskScore: Number(formData.riskScore) || 25,
        documentToken: documentToken || null,
        contractFileName: uploadedFileName || selectedFile?.name || null,
      };

      const res = await createSupplier(payload);
      if (res && res.status === 'success' && res.data) {
        setCreatedSupplier(res.data);
        if (onSupplierCreated) onSupplierCreated(res.data);
      } else {
        setSubmitError(res?.message || 'Failed to create supplier.');
      }
    } catch (err) {
      setSubmitError(err.message || 'Error occurred while creating supplier.');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Helper to render field status badge and evidence button
  const renderFieldStatus = (fieldKey, metaKey) => {
    if (!extractedMeta) return null;

    const meta = extractedMeta[metaKey];
    const isEdited = editedFields.has(fieldKey);
    const hasExtractedVal = meta && meta.value;

    if (isEdited) {
      return (
        <span
          className="inline-flex items-center gap-1 text-[11px] font-medium text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full border border-amber-200"
          title="Value modified by user"
        >
          <Edit3 size={11} /> User Edited
        </span>
      );
    }

    if (hasExtractedVal) {
      const confPercent = Math.round((meta.confidence || 0.9) * 100);
      const isPopoverOpen = activeEvidenceField === fieldKey;

      return (
        <div className="relative inline-flex items-center gap-1.5">
          <span
            className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200"
            title={`Extracted with ${confPercent}% confidence`}
          >
            <Sparkles size={11} className="text-emerald-600" />
            AI Extracted ({confPercent}%)
          </span>

          {meta.source && (
            <button
              type="button"
              className="text-gray-400 hover:text-primary-600 transition-colors p-0.5 rounded hover:bg-gray-100"
              onClick={() => setActiveEvidenceField(isPopoverOpen ? null : fieldKey)}
              title="View contract source evidence"
            >
              <Info size={13} className={isPopoverOpen ? 'text-primary-600' : ''} />
            </button>
          )}

          {/* Evidence Popover */}
          {isPopoverOpen && meta.source && (
            <div
              className="absolute right-0 bottom-full mb-1.5 z-30 w-72 bg-white rounded-lg shadow-xl border border-gray-200 p-3 text-xs text-gray-700 animate-fade-in"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between pb-1.5 mb-1.5 border-b border-gray-100 font-semibold text-gray-800">
                <span className="flex items-center gap-1 text-primary-700">
                  <ShieldCheck size={13} /> Source Evidence
                </span>
                <span className="text-emerald-600 font-mono text-[10px]">{confPercent}% Conf.</span>
              </div>
              <p className="text-gray-600 leading-relaxed font-mono text-[11px] bg-gray-50 p-2 rounded border border-gray-100">
                {meta.source}
              </p>
              <div className="mt-2 text-right">
                <button
                  type="button"
                  className="text-[10px] text-gray-500 hover:text-gray-800 underline"
                  onClick={() => setActiveEvidenceField(null)}
                >
                  Dismiss
                </button>
              </div>
            </div>
          )}
        </div>
      );
    }

    return (
      <span className="text-[11px] text-gray-400 italic">
        Not detected in contract (Manual entry)
      </span>
    );
  };

  return (
    <div className="evidence-modal-overlay" onClick={onClose}>
      <div
        className="evidence-modal"
        style={{ maxWidth: '780px', maxHeight: '92vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="evidence-modal-header border-b border-gray-200 px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-primary-100 text-primary-700 flex items-center justify-center font-bold">
              <Sparkles size={18} />
            </div>
            <div>
              <h3 className="font-bold text-gray-900 text-lg leading-tight">
                {createdSupplier ? 'Supplier Onboarded Successfully!' : 'Add New Supplier Partner'}
              </h3>
              <p className="text-xs text-gray-500">
                {createdSupplier
                  ? 'Supplier and contract record registered in database'
                  : 'AI-Powered Contract Extraction & Intelligent Onboarding'}
              </p>
            </div>
          </div>
          <button className="evidence-modal-close" onClick={onClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        {/* Modal Body */}
        <div className="evidence-modal-body p-6 overflow-y-auto">
          {createdSupplier ? (
            /* Success State Screen */
            <div className="text-center py-4">
              <div className="w-16 h-16 bg-emerald-100 text-emerald-600 rounded-full flex items-center justify-center mx-auto mb-4 shadow-sm">
                <CheckCircle size={36} />
              </div>
              <h4 className="text-xl font-bold text-gray-900 mb-1">
                {createdSupplier.name}
              </h4>
              <p className="text-xs font-mono text-gray-500 mb-4">
                Supplier ID: <span className="font-bold text-primary-700">{createdSupplier.id}</span>
              </p>

              <p className="text-sm text-gray-600 max-w-lg mx-auto mb-6">
                Supplier partner record created successfully in PostgreSQL.
                {createdSupplier.contract ? (
                  <span className="block mt-1 text-emerald-700 font-medium">
                    Contract document successfully ingested, parsed, and indexed into Qdrant & BM25 hybrid vector store for RAG queries!
                  </span>
                ) : (
                  <span className="block mt-1 text-gray-500">
                    You can now upload contracts, track purchases, or inspect performance.
                  </span>
                )}
              </p>

              {/* Summary Card */}
              <div className="bg-gray-50 p-4 rounded-xl border border-gray-200 text-left mb-6 max-w-lg mx-auto space-y-2.5 text-sm">
                <div className="flex justify-between items-center py-1 border-b border-gray-200/60">
                  <span className="text-gray-500 text-xs uppercase tracking-wider font-semibold">Category:</span>
                  <span className="font-semibold text-gray-800">{createdSupplier.category}</span>
                </div>
                <div className="flex justify-between items-center py-1 border-b border-gray-200/60">
                  <span className="text-gray-500 text-xs uppercase tracking-wider font-semibold">Location / Country:</span>
                  <span className="font-semibold text-gray-800">{createdSupplier.location}</span>
                </div>
                <div className="flex justify-between items-center py-1 border-b border-gray-200/60">
                  <span className="text-gray-500 text-xs uppercase tracking-wider font-semibold">Primary Contact:</span>
                  <span className="font-semibold text-gray-800">{createdSupplier.contactPerson || 'Not specified'}</span>
                </div>
                <div className="flex justify-between items-center py-1 border-b border-gray-200/60">
                  <span className="text-gray-500 text-xs uppercase tracking-wider font-semibold">Contact Email:</span>
                  <span className="font-semibold text-gray-800">{createdSupplier.contactEmail || 'Not specified'}</span>
                </div>
                <div className="flex justify-between items-center py-1">
                  <span className="text-gray-500 text-xs uppercase tracking-wider font-semibold">Initial Status:</span>
                  <span className="capitalize font-semibold text-emerald-600">{createdSupplier.status || 'Active'}</span>
                </div>
              </div>

              {/* Actions */}
              <div className="flex flex-col sm:flex-row gap-3 justify-center">
                <button
                  type="button"
                  className="btn btn-primary flex items-center justify-center gap-2 px-5 py-2.5 shadow-md"
                  onClick={() => {
                    onClose();
                    navigate(`/suppliers/${createdSupplier.id}/overview`);
                  }}
                >
                  <FileText size={18} /> View Supplier 360 →
                </button>
                <button
                  type="button"
                  className="btn btn-secondary flex items-center justify-center gap-2 px-5 py-2.5"
                  onClick={onClose}
                >
                  Done
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              {/* SECTION 1: AI-Powered Supplier Information Extraction */}
              <div className="rounded-xl border border-indigo-100 bg-gradient-to-b from-indigo-50/50 to-white p-5 shadow-sm">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Sparkles className="text-primary-600" size={18} />
                    <h4 className="font-semibold text-gray-900 text-sm tracking-wide">
                      AI-Powered Supplier Information Extraction
                    </h4>
                  </div>
                  <span className="text-[11px] font-medium text-primary-700 bg-primary-50 px-2 py-0.5 rounded-full border border-primary-200">
                    RAG Pipeline
                  </span>
                </div>
                <p className="text-xs text-gray-600 mb-3">
                  Upload a new contract or select an already-uploaded document. Our hybrid RAG pipeline will automatically analyze clauses, extract contracting parties, address, category, and verified contacts.
                </p>

                {/* Mode Selector: Upload New vs Select Existing */}
                <div className="flex items-center gap-2 mb-4 p-1 bg-gray-100 rounded-lg w-fit">
                  <button
                    type="button"
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                      inputMode === 'upload'
                        ? 'bg-white text-gray-900 shadow-xs'
                        : 'text-gray-600 hover:text-gray-900'
                    }`}
                    onClick={() => {
                      setInputMode('upload');
                      setSelectedExistingDoc(null);
                    }}
                  >
                    <Upload size={13} />
                    <span>Upload New File</span>
                  </button>
                  <button
                    type="button"
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                      inputMode === 'existing'
                        ? 'bg-white text-gray-900 shadow-xs'
                        : 'text-gray-600 hover:text-gray-900'
                    }`}
                    onClick={() => {
                      setInputMode('existing');
                      setSelectedFile(null);
                    }}
                  >
                    <FolderOpen size={13} />
                    <span>Select Already-Uploaded Contract ({availableDocs.length})</span>
                  </button>
                </div>

                {inputMode === 'upload' ? (
                  /* Drag and Drop Area */
                  <div
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    className={`border-2 border-dashed rounded-xl p-5 text-center transition-all cursor-pointer ${
                      isDragging
                        ? 'border-primary-500 bg-primary-50/70 scale-[0.99]'
                        : selectedFile
                        ? 'border-emerald-300 bg-emerald-50/30'
                        : 'border-gray-300 hover:border-primary-400 bg-gray-50/60 hover:bg-white'
                    }`}
                    onClick={() => {
                      if (!selectedFile && fileInputRef.current) {
                        fileInputRef.current.click();
                      }
                    }}
                  >
                    <input
                      type="file"
                      ref={fileInputRef}
                      className="hidden"
                      accept=".pdf,.docx,.doc,.txt"
                      onChange={handleFileInputChange}
                    />

                    {selectedFile ? (
                      <div className="flex items-center justify-between gap-3 text-left">
                        <div className="flex items-center gap-3 min-w-0">
                          <div className="w-10 h-10 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center shrink-0">
                            <FileCheck size={22} />
                          </div>
                          <div className="min-w-0">
                            <p className="font-medium text-gray-900 text-sm truncate">
                              {selectedFile.name}
                            </p>
                            <p className="text-xs text-gray-500">
                              {formatFileSize(selectedFile.size)} • Ready for extraction
                            </p>
                          </div>
                        </div>

                        <div className="flex items-center gap-2 shrink-0">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleClearFile();
                            }}
                            className="btn btn-secondary btn-sm text-gray-500 hover:text-red-600 p-1.5"
                            title="Remove file"
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="py-2">
                        <div className="w-10 h-10 rounded-full bg-primary-100 text-primary-600 flex items-center justify-center mx-auto mb-2">
                          <Upload size={20} />
                        </div>
                        <p className="text-xs font-semibold text-gray-800 mb-0.5">
                          Drag and drop your supplier contract here, or{' '}
                          <span className="text-primary-600 underline">browse files</span>
                        </p>
                        <p className="text-[11px] text-gray-500">
                          Supports PDF and DOCX documents (up to 20 MB)
                        </p>
                      </div>
                    )}
                  </div>
                ) : (
                  /* Select from Already-Uploaded Contracts */
                  <div className="space-y-3">
                    <div className="input-with-icon">
                      <Search size={14} className="input-icon" />
                      <input
                        type="text"
                        className="input text-xs"
                        placeholder="Search uploaded contracts by company name or filename..."
                        value={docFilter}
                        onChange={(e) => setDocFilter(e.target.value)}
                      />
                    </div>

                    {docsLoading ? (
                      <div className="text-center py-4 text-xs text-gray-500">
                        Loading existing contract documents...
                      </div>
                    ) : availableDocs.length === 0 ? (
                      <div className="text-center py-4 text-xs text-gray-500 bg-gray-50 rounded-lg border border-gray-200">
                        No previous contract documents found in system. Please upload a contract file.
                      </div>
                    ) : (
                      <div className="max-h-48 overflow-y-auto space-y-1.5 pr-1">
                        {availableDocs
                          .filter(
                            (d) =>
                              d.filename.toLowerCase().includes(docFilter.toLowerCase()) ||
                              (d.displayName || '').toLowerCase().includes(docFilter.toLowerCase())
                          )
                          .map((doc, idx) => (
                            <div
                              key={idx}
                              onClick={() => setSelectedExistingDoc(doc)}
                              className={`p-2.5 rounded-lg border text-left cursor-pointer transition-all flex items-center justify-between gap-2 ${
                                selectedExistingDoc?.filename === doc.filename
                                  ? 'border-primary-500 bg-primary-50/70 shadow-xs ring-1 ring-primary-500'
                                  : 'border-gray-200 hover:border-gray-300 bg-white hover:bg-gray-50'
                              }`}
                            >
                              <div className="flex items-center gap-2.5 min-w-0">
                                <FileText
                                  size={16}
                                  className={
                                    selectedExistingDoc?.filename === doc.filename
                                      ? 'text-primary-600 shrink-0'
                                      : 'text-gray-400 shrink-0'
                                  }
                                />
                                <div className="min-w-0">
                                  <p className="text-xs font-semibold text-gray-900 truncate">
                                    {doc.displayName || doc.filename}
                                  </p>
                                  <p className="text-[10px] text-gray-500 font-mono truncate">
                                    {doc.filename} {doc.fileSize > 0 ? `• ${formatFileSize(doc.fileSize)}` : ''}
                                  </p>
                                </div>
                              </div>
                              {doc.contractId && (
                                <span className="badge badge-info text-[10px] shrink-0">
                                  {doc.contractId}
                                </span>
                              )}
                            </div>
                          ))}
                      </div>
                    )}

                    {selectedExistingDoc && (
                      <div className="p-3 bg-indigo-50/70 border border-indigo-200 rounded-lg flex items-center justify-between gap-3 text-xs">
                        <div className="flex items-center gap-2">
                          <CheckCircle size={15} className="text-primary-600 shrink-0" />
                          <span className="font-medium text-gray-900">
                            Selected: <strong>{selectedExistingDoc.displayName || selectedExistingDoc.filename}</strong>
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={() => setSelectedExistingDoc(null)}
                          className="text-gray-500 hover:text-red-600"
                        >
                          <X size={14} />
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {/* Upload & Extract Action Button (for file upload) */}
                {inputMode === 'upload' && selectedFile && !extractedMeta && !isExtracting && (
                  <div className="mt-3 flex justify-end">
                    <button
                      type="button"
                      onClick={handleExtractDetails}
                      className="btn btn-primary flex items-center gap-2 text-xs py-2 px-4 shadow-sm"
                    >
                      <Sparkles size={14} /> Upload & Extract Details
                    </button>
                  </div>
                )}

                {/* Extract from Selected Existing Document Action Button */}
                {inputMode === 'existing' && selectedExistingDoc && !extractedMeta && !isExtracting && (
                  <div className="mt-3 flex justify-end">
                    <button
                      type="button"
                      onClick={handleExtractExistingDetails}
                      className="btn btn-primary flex items-center gap-2 text-xs py-2 px-4 shadow-sm"
                    >
                      <Sparkles size={14} /> Extract Details from This Document
                    </button>
                  </div>
                )}

                {/* Extracting Loading State */}
                {isExtracting && (
                  <div className="mt-4 p-4 bg-white rounded-lg border border-primary-100 shadow-xs">
                    <div className="flex items-center justify-between text-xs font-medium text-gray-700 mb-2">
                      <span className="flex items-center gap-2 text-primary-700">
                        <RefreshCw size={13} className="animate-spin text-primary-600" />
                        {extractionStatusText}
                      </span>
                      <span className="font-mono text-primary-600">{extractionProgress}%</span>
                    </div>
                    <div className="w-full bg-gray-100 rounded-full h-1.5 overflow-hidden">
                      <div
                        className="bg-primary-600 h-1.5 rounded-full transition-all duration-300"
                        style={{ width: `${extractionProgress}%` }}
                      ></div>
                    </div>
                  </div>
                )}

                {/* Extraction Error */}
                {extractionError && (
                  <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700 flex items-center gap-2">
                    <AlertTriangle size={15} className="shrink-0 text-red-600" />
                    <span>{extractionError}</span>
                  </div>
                )}

                {/* Extraction Results Info Banner */}
                {extractedMeta && (
                  <div className="mt-3 p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-xs text-emerald-800 flex items-start gap-2.5">
                    <CheckCircle size={16} className="text-emerald-600 shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <p className="font-semibold">
                        Contract extracted successfully from {uploadedFileName}!
                      </p>
                      <p className="text-[11px] text-emerald-700 mt-0.5">
                        Fields have been automatically populated below. Review and edit any field before confirming supplier creation.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={handleClearFile}
                      className="text-[11px] text-emerald-700 hover:text-emerald-900 underline shrink-0"
                    >
                      Reset File
                    </button>
                  </div>
                )}

                {/* Duplicate Supplier Alert */}
                {extractedMeta?.is_duplicate && extractedMeta?.existing_supplier && (
                  <div className="mt-3 p-3 bg-amber-50 border border-amber-300 rounded-lg text-xs text-amber-900 flex items-start gap-2">
                    <AlertTriangle size={16} className="text-amber-600 shrink-0 mt-0.5" />
                    <div>
                      <span className="font-semibold">Potential Duplicate Supplier Detected:</span> A supplier named{' '}
                      <strong>{extractedMeta.existing_supplier.name}</strong> is already registered with ID{' '}
                      <span className="font-mono font-bold">{extractedMeta.existing_supplier.id}</span>.
                      Please verify or adjust the name before saving.
                    </div>
                  </div>
                )}

                {/* Multiple Candidate Entities Detected */}
                {extractedMeta?.multiple_candidates && extractedMeta.multiple_candidates.length > 0 && (
                  <div className="mt-3 p-3 bg-blue-50/80 border border-blue-200 rounded-lg text-xs text-blue-900">
                    <p className="font-semibold mb-1 flex items-center gap-1.5">
                      <Building2 size={13} className="text-blue-600" />
                      Multiple contracting entities detected in agreement:
                    </p>
                    <div className="flex flex-wrap gap-2 mt-1.5">
                      {extractedMeta.multiple_candidates.map((cand, idx) => (
                        <button
                          key={idx}
                          type="button"
                          onClick={() => handleSelectCandidate(cand)}
                          className={`px-2.5 py-1 rounded text-xs border transition-all ${
                            formData.name === cand.name
                              ? 'bg-blue-600 text-white border-blue-600 shadow-xs'
                              : 'bg-white text-blue-800 border-blue-300 hover:bg-blue-100'
                          }`}
                        >
                          <strong>{cand.name}</strong>
                          {cand.role && <span className="opacity-80 text-[10px] ml-1">({cand.role})</span>}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* SECTION 2: Form Details (Human Review & Edit) */}
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="flex items-center justify-between pb-1 border-b border-gray-100">
                  <span className="text-xs font-bold text-gray-800 uppercase tracking-wider">
                    Supplier Partner Details
                  </span>
                  <span className="text-[11px] text-gray-500">
                    * Required field • All fields are manually editable
                  </span>
                </div>

                {submitError && (
                  <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700 flex items-center gap-2">
                    <AlertTriangle size={15} className="shrink-0 text-red-600" />
                    <span>{submitError}</span>
                  </div>
                )}

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {/* Supplier / Company Name */}
                  <div className="sm:col-span-2">
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-xs font-semibold text-gray-700 uppercase tracking-wider">
                        Supplier / Company Name *
                      </label>
                      {renderFieldStatus('name', 'supplier_name')}
                    </div>
                    <input
                      type="text"
                      name="name"
                      required
                      className="input w-full"
                      placeholder="e.g. Tata Advanced Systems, Precision Machining Corp"
                      value={formData.name}
                      onChange={handleFormChange}
                    />
                  </div>

                  {/* Category */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-xs font-semibold text-gray-700 uppercase tracking-wider">
                        Category
                      </label>
                      {renderFieldStatus('category', 'category')}
                    </div>
                    <select
                      name="category"
                      className="select w-full"
                      value={formData.category}
                      onChange={handleFormChange}
                    >
                      {availableCategories.map((cat) => (
                        <option key={cat} value={cat}>
                          {cat}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Location / Country */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-xs font-semibold text-gray-700 uppercase tracking-wider">
                        Location / Country
                      </label>
                      {renderFieldStatus('location', 'location')}
                    </div>
                    <input
                      type="text"
                      name="location"
                      className="input w-full"
                      placeholder="e.g. Pune, India / Berlin, Germany"
                      value={formData.location}
                      onChange={handleFormChange}
                    />
                  </div>

                  {/* Contact Person */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-xs font-semibold text-gray-700 uppercase tracking-wider">
                        Contact Person
                      </label>
                      {renderFieldStatus('contactPerson', 'contact_person')}
                    </div>
                    <input
                      type="text"
                      name="contactPerson"
                      className="input w-full"
                      placeholder="e.g. Vikram Sharma"
                      value={formData.contactPerson}
                      onChange={handleFormChange}
                    />
                  </div>

                  {/* Contact Email */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-xs font-semibold text-gray-700 uppercase tracking-wider">
                        Contact Email
                      </label>
                      {renderFieldStatus('contactEmail', 'contact_email')}
                    </div>
                    <input
                      type="email"
                      name="contactEmail"
                      className="input w-full"
                      placeholder="e.g. vikram@supplier.com"
                      value={formData.contactEmail}
                      onChange={handleFormChange}
                    />
                  </div>

                  {/* Contact Phone */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-xs font-semibold text-gray-700 uppercase tracking-wider">
                        Contact Phone
                      </label>
                      {renderFieldStatus('contactPhone', 'contact_phone')}
                    </div>
                    <input
                      type="tel"
                      name="contactPhone"
                      className="input w-full"
                      placeholder="e.g. +91 98765 43210"
                      value={formData.contactPhone}
                      onChange={handleFormChange}
                    />
                  </div>

                  {/* Initial Relationship Status */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-xs font-semibold text-gray-700 uppercase tracking-wider">
                        Initial Relationship Status
                      </label>
                      <span className="text-[11px] text-gray-400 italic">User selection</span>
                    </div>
                    <select
                      name="status"
                      className="select w-full"
                      value={formData.status}
                      onChange={handleFormChange}
                    >
                      <option value="active">Active</option>
                      <option value="under_review">Under Review</option>
                      <option value="inactive">Inactive</option>
                    </select>
                  </div>
                </div>

                {/* Form Footer */}
                <div className="pt-4 border-t border-gray-200 flex items-center justify-between">
                  <div className="text-xs text-gray-500">
                    {documentToken ? (
                      <span className="flex items-center gap-1.5 text-emerald-700 font-medium">
                        <FileCheck size={14} /> Contract ready to be indexed upon creation
                      </span>
                    ) : (
                      <span>Manual onboarding mode active</span>
                    )}
                  </div>
                  <div className="flex gap-3">
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={onClose}
                      disabled={isSubmitting || isExtracting}
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      className="btn btn-primary flex items-center gap-1.5"
                      disabled={isSubmitting || isExtracting || !formData.name.trim()}
                    >
                      {isSubmitting ? (
                        <>
                          <RefreshCw size={14} className="animate-spin" />
                          Creating Supplier...
                        </>
                      ) : (
                        'Create Supplier Partner'
                      )}
                    </button>
                  </div>
                </div>
              </form>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
