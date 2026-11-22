import { useState, useRef, useEffect } from 'react';
import { useOutletContext, Link } from 'react-router-dom';
import { 
  FileText, BarChart3, IndianRupee, RefreshCw, MessageSquare, 
  Send, CheckCircle, AlertTriangle, Info, Bot, Upload, Sparkles,
  Plus, Search, Trash2, Edit3, MoreHorizontal, FolderOpen, Check, X,
  ExternalLink
} from 'lucide-react';
import { EvidenceModal } from '../components/ui';
import MarketPriceBenchmarking from '../components/pricing/MarketPriceBenchmarking';
import { 
  runAnalysis, 
  sendAssistantMessage, 
  getContractBySupplier,
  getChatSessions,
  createChatSession,
  getSessionMessages,
  sendSessionMessage,
  renameChatSession,
  deleteChatSession,
} from '../services';

function groupSessionsByDate(sessions) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const last7 = new Date(today);
  last7.setDate(last7.getDate() - 7);
  const last30 = new Date(today);
  last30.setDate(last30.getDate() - 30);

  const groups = {
    'Today': [],
    'Yesterday': [],
    'Previous 7 Days': [],
    'Previous 30 Days': [],
    'Older': [],
  };

  for (const s of sessions) {
    const d = new Date(s.updated_at || s.created_at);
    if (d >= today) groups['Today'].push(s);
    else if (d >= yesterday) groups['Yesterday'].push(s);
    else if (d >= last7) groups['Previous 7 Days'].push(s);
    else if (d >= last30) groups['Previous 30 Days'].push(s);
    else groups['Older'].push(s);
  }

  return Object.entries(groups).filter(([, items]) => items.length > 0);
}

export default function AIAnalysis() {
  const { supplier } = useOutletContext();
  const [activeAnalysis, setActiveAnalysis] = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [activeContract, setActiveContract] = useState(null);
  
  // Chat state with persistent history & ChatGPT-style sidebar
  const [chatOpen, setChatOpen] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [editingSessionId, setEditingSessionId] = useState(null);
  const [editTitle, setEditTitle] = useState('');
  const [contextMenuSessionId, setContextMenuSessionId] = useState(null);

  const [messages, setMessages] = useState([
    { 
      role: 'assistant', 
      content: `Hello! I'm your AI Procurement Assistant. How can I help you analyze ${supplier.name}?`,
      timestamp: new Date().toISOString()
    }
  ]);
  const [inputMessage, setInputMessage] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Evidence Modal State
  const [evidenceModalOpen, setEvidenceModalOpen] = useState(false);
  const [evidenceData, setEvidenceData] = useState([]);
  const [evidenceTitle, setEvidenceTitle] = useState('');

  // Close context menu on click outside
  useEffect(() => {
    const handler = () => setContextMenuSessionId(null);
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, []);

  // Load chat sessions when chat is opened
  useEffect(() => {
    if (chatOpen) {
      loadSessions();
    }
  }, [chatOpen, supplier.id]);

  const loadSessions = async () => {
    setSessionsLoading(true);
    try {
      const res = await getChatSessions(supplier.id);
      if (res.status === 'success' && res.data) {
        setSessions(res.data);
      }
    } catch (err) {
      console.error('Failed to load sessions:', err);
    } finally {
      setSessionsLoading(false);
    }
  };

  const loadSessionMessages = async (sessionId) => {
    setMessagesLoading(true);
    try {
      const res = await getSessionMessages(sessionId);
      if (res.status === 'success' && res.data) {
        const loaded = res.data.messages.map(m => ({
          role: m.role,
          content: m.content,
          keyFindings: m.key_findings || [],
          evidence: m.evidence || [],
          suggestedActions: m.suggested_actions || [],
          timestamp: m.timestamp,
        }));
        setMessages(loaded.length > 0 ? loaded : [
          {
            role: 'assistant',
            content: `Resumed chat about ${supplier.name}. What would you like to explore?`,
            timestamp: new Date().toISOString(),
          }
        ]);
      }
    } catch (err) {
      console.error('Failed to load messages:', err);
    } finally {
      setMessagesLoading(false);
    }
  };

  const handleSelectSession = async (sessionId) => {
    setActiveSessionId(sessionId);
    setContextMenuSessionId(null);
    await loadSessionMessages(sessionId);
  };

  const handleNewChat = () => {
    setActiveSessionId(null);
    setMessages([
      {
        role: 'assistant',
        content: `New chat started for ${supplier.name}. Ask me anything about contracts, delivery SLAs, payment terms, or pricing!`,
        timestamp: new Date().toISOString(),
      }
    ]);
    setTimeout(() => inputRef.current?.focus(), 100);
  };

  const handleDeleteSession = async (sessionId) => {
    try {
      await deleteChatSession(sessionId);
      setSessions(prev => prev.filter(s => s.session_id !== sessionId));
      if (activeSessionId === sessionId) {
        handleNewChat();
      }
    } catch (err) {
      console.error('Failed to delete session:', err);
    }
    setContextMenuSessionId(null);
  };

  const handleStartRename = (session) => {
    setEditingSessionId(session.session_id);
    setEditTitle(session.title);
    setContextMenuSessionId(null);
  };

  const handleSaveRename = async () => {
    if (editingSessionId && editTitle.trim()) {
      try {
        await renameChatSession(editingSessionId, editTitle.trim());
        setSessions(prev =>
          prev.map(s =>
            s.session_id === editingSessionId ? { ...s, title: editTitle.trim() } : s
          )
        );
      } catch (err) {
        console.error('Failed to rename session:', err);
      }
    }
    setEditingSessionId(null);
    setEditTitle('');
  };

  useEffect(() => {
    async function checkContract() {
      try {
        const res = await getContractBySupplier(supplier.id);
        if (res.status === 'success' && res.data) {
          setActiveContract(res.data);
        } else {
          setActiveContract(null);
        }
      } catch (err) {
        setActiveContract(null);
      }
    }
    checkContract();
  }, [supplier.id]);


  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    if (chatOpen) {
      scrollToBottom();
    }
  }, [messages, chatOpen, isTyping]);

  const handleRunAnalysis = async (type) => {
    setActiveAnalysis(type);
    if (type === 'pricing_analysis') {
      // Handled directly by MarketPriceBenchmarking component
      return;
    }
    setLoading(true);
    setAnalysisResult(null);
    
    try {
      const res = await runAnalysis(supplier.id, type);
      if (res.status === 'success') {
        setAnalysisResult(res.data);
      }
    } catch (error) {
      console.error("Analysis failed:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleSendMessage = async (e) => {
    e.preventDefault();
    if (!inputMessage.trim() || isTyping) return;

    const userMsg = inputMessage.trim();
    setInputMessage('');
    
    // Add user message to UI immediately
    setMessages(prev => [...prev, {
      role: 'user',
      content: userMsg,
      timestamp: new Date().toISOString()
    }]);
    
    setIsTyping(true);
    
    try {
      let sessionId = activeSessionId;

      // Auto-create session if none active
      if (!sessionId) {
        const createRes = await createChatSession(supplier.id, supplier.name, userMsg.slice(0, 50));
        if (createRes.status === 'success' && createRes.data) {
          sessionId = createRes.data.session_id;
          setActiveSessionId(sessionId);
          setSessions(prev => [createRes.data, ...prev]);
        }
      }

      // Send message within session to persist both turns
      if (sessionId) {
        const res = await sendSessionMessage(sessionId, userMsg, supplier.id);
        if (res.status === 'success' && res.data) {
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: res.data.content,
            keyFindings: res.data.keyFindings || [],
            evidence: res.data.evidence || [],
            suggestedActions: res.data.suggestedActions || [],
            timestamp: res.data.timestamp,
          }]);

          if (res.data.session_title) {
            setSessions(prev =>
              prev.map(s =>
                s.session_id === sessionId
                  ? { ...s, title: res.data.session_title, updated_at: new Date().toISOString(), message_count: (s.message_count || 0) + 2 }
                  : s
              )
            );
          }
        }
      } else {
        // Fallback to direct assistant query
        const res = await sendAssistantMessage(supplier.id, userMsg);
        if (res.status === 'success') {
          setMessages(prev => [...prev, res.data]);
        }
      }
    } catch (error) {
      console.error("Chat failed:", error);
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'I encountered an error while processing your request. Please try again.',
        timestamp: new Date().toISOString()
      }]);
    } finally {
      setIsTyping(false);
    }
  };

  const openEvidence = (evidence, title = 'Supporting Evidence') => {
    if (!evidence || evidence.length === 0) return;
    setEvidenceTitle(title);
    setEvidenceData(evidence);
    setEvidenceModalOpen(true);
  };

  const renderFindingIcon = (severity) => {
    switch (severity) {
      case 'success': return <CheckCircle size={18} className="finding-icon success" />;
      case 'warning': return <AlertTriangle size={18} className="finding-icon warning" />;
      case 'error': return <AlertTriangle size={18} className="finding-icon error" />;
      default: return <Info size={18} className="finding-icon info" />;
    }
  };

  return (
    <div className="animate-fade-in">
      <EvidenceModal 
        isOpen={evidenceModalOpen}
        onClose={() => setEvidenceModalOpen(false)}
        title={evidenceTitle}
        evidence={evidenceData}
      />

      {/* Grounding Info Bar */}
      <div className="card mb-6 bg-gradient-to-r from-blue-50/70 via-indigo-50/70 to-purple-50/70 border border-blue-200">
        <div className="card-body p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary-600 text-white flex items-center justify-center flex-shrink-0 shadow-sm">
              <Bot size={22} />
            </div>
            <div>
              <div className="font-bold text-gray-900 flex items-center gap-2">
                <span>Agentic AI Grounding: {supplier.name}</span>
                <span className="badge badge-info">{supplier.id}</span>
              </div>
              <div className="text-xs text-gray-600 mt-1 flex flex-wrap items-center gap-2">
                <span>Contract Source:</span>
                {activeContract ? (
                  <span className="font-semibold text-emerald-800 bg-emerald-100 px-2.5 py-0.5 rounded-full border border-emerald-200 flex items-center gap-1">
                    <CheckCircle size={12} /> {activeContract.contractTitle || activeContract.documents?.[0]?.name || 'Active Contract Document'}
                  </span>
                ) : (
                  <span className="font-medium text-amber-800 bg-amber-100 px-2.5 py-0.5 rounded-full border border-amber-200 flex items-center gap-1">
                    <AlertTriangle size={12} /> No Contract Uploaded Yet (Using baseline profile)
                  </span>
                )}
              </div>
            </div>
          </div>
          <Link
            to={`/documents?supplierId=${supplier.id}`}
            className="btn btn-secondary btn-sm flex items-center justify-center gap-1.5 whitespace-nowrap self-start sm:self-auto"
          >
            <Upload size={14} /> {activeContract ? 'Upload New Contract Version' : 'Upload Contract for this Supplier'}
          </Link>
        </div>
      </div>

      {!activeAnalysis && !chatOpen ? (
        <div className="action-card-grid">
          <div className="action-card" onClick={() => handleRunAnalysis('contract_analysis')}>
            <div className="action-card-icon blue"><FileText size={28} /></div>
            <h3 className="action-card-title">Analyze Contract</h3>
            <p className="action-card-description">Review contract terms, obligations, and identify potential risks or missing clauses.</p>
          </div>
          
          <div className="action-card" onClick={() => handleRunAnalysis('performance_review')}>
            <div className="action-card-icon green"><BarChart3 size={28} /></div>
            <h3 className="action-card-title">Review Performance</h3>
            <p className="action-card-description">Analyze delivery trends, quality metrics, and operational reliability over time.</p>
          </div>
          
          <div className="action-card" onClick={() => handleRunAnalysis('pricing_analysis')}>
            <div className="action-card-icon orange"><IndianRupee size={28} /></div>
            <h3 className="action-card-title">Analyze Pricing</h3>
            <p className="action-card-description">Compare current pricing against historical data, market rates, and identify trends.</p>
          </div>
          
          <div className="action-card" onClick={() => handleRunAnalysis('renewal_review')}>
            <div className="action-card-icon purple"><RefreshCw size={28} /></div>
            <h3 className="action-card-title">Renewal Review</h3>
            <p className="action-card-description">Comprehensive synthesis of contract, performance, and pricing for upcoming renewals.</p>
          </div>
          
          <div className="action-card" onClick={() => setChatOpen(true)}>
            <div className="action-card-icon teal"><MessageSquare size={28} /></div>
            <h3 className="action-card-title">Ask Supplier Assistant</h3>
            <p className="action-card-description">Chat with our AI assistant to get specific answers about this supplier.</p>
          </div>
        </div>
      ) : activeAnalysis === 'pricing_analysis' ? (
        <MarketPriceBenchmarking supplier={supplier} onBack={() => setActiveAnalysis(null)} />
      ) : activeAnalysis ? (
        <div className="card">
          <div className="card-header bg-gray-50 flex items-center justify-between">
            <h2 className="card-title text-xl font-bold capitalize">
              {activeAnalysis.replace('_', ' ')}
            </h2>
            <button className="btn btn-secondary btn-sm" onClick={() => setActiveAnalysis(null)}>
              Back to Actions
            </button>
          </div>
          
          <div className="card-body">
            {loading ? (
              <div className="loading-container py-20">
                <div className="loading-spinner"></div>
                <div className="loading-text">Agents are investigating...</div>
              </div>
            ) : analysisResult ? (
              <div className="animate-fade-in">
                <div className="mb-8 p-6 bg-indigo-50 border border-indigo-100 rounded-lg">
                  <div className="flex gap-4">
                    <Bot size={24} className="text-primary-600 flex-shrink-0" />
                    <div>
                      <h3 className="font-semibold text-gray-900 mb-2">Executive Summary</h3>
                      <p className="text-gray-700 leading-relaxed">{analysisResult.summary}</p>
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-8">
                  {analysisResult.contractFindings?.length > 0 && (
                    <div>
                      <h3 className="font-semibold text-gray-900 mb-4 pb-2 border-b border-gray-200">Contract Findings</h3>
                      <div className="flex flex-col gap-1">
                        {analysisResult.contractFindings.map((finding, idx) => (
                          <div key={idx} className="finding-item">
                            {renderFindingIcon(finding.severity)}
                            <div className="finding-content">
                              <div className="finding-message">{finding.message}</div>
                              {finding.evidence && (
                                <div className="finding-actions">
                                  <button 
                                    className="evidence-trigger"
                                    onClick={() => openEvidence(finding.evidence, 'Contract Evidence')}
                                  >
                                    View Evidence
                                  </button>
                                </div>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {analysisResult.performanceFindings?.length > 0 && (
                    <div>
                      <h3 className="font-semibold text-gray-900 mb-4 pb-2 border-b border-gray-200">Performance Findings</h3>
                      <div className="flex flex-col gap-1">
                        {analysisResult.performanceFindings.map((finding, idx) => (
                          <div key={idx} className="finding-item">
                            {renderFindingIcon(finding.severity)}
                            <div className="finding-content">
                              <div className="finding-message">{finding.message}</div>
                              {finding.evidence && (
                                <div className="finding-actions">
                                  <button 
                                    className="evidence-trigger"
                                    onClick={() => openEvidence(finding.evidence, 'Performance Evidence')}
                                  >
                                    View Evidence
                                  </button>
                                </div>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {analysisResult.pricingFindings?.length > 0 && (
                    <div>
                      <h3 className="font-semibold text-gray-900 mb-4 pb-2 border-b border-gray-200">Pricing Findings</h3>
                      <div className="flex flex-col gap-1">
                        {analysisResult.pricingFindings.map((finding, idx) => (
                          <div key={idx} className="finding-item">
                            {renderFindingIcon(finding.severity)}
                            <div className="finding-content">
                              <div className="finding-message">{finding.message}</div>
                              {finding.evidence && (
                                <div className="finding-actions">
                                  <button 
                                    className="evidence-trigger"
                                    onClick={() => openEvidence(finding.evidence, 'Pricing Evidence')}
                                  >
                                    View Evidence
                                  </button>
                                </div>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {analysisResult.discussionPoints?.length > 0 && (
                    <div>
                      <h3 className="font-semibold text-gray-900 mb-4 pb-2 border-b border-gray-200">Suggested Discussion Points</h3>
                      <ul className="list-disc pl-5 text-gray-700 space-y-2">
                        {analysisResult.discussionPoints.map((point, idx) => (
                          <li key={idx} className="pl-1">{point}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
                
                {analysisResult.evidence?.length > 0 && (
                  <div className="mt-4 pt-4 border-t border-gray-200 text-center">
                    <button 
                      className="btn btn-secondary"
                      onClick={() => openEvidence(analysisResult.evidence, 'All Supporting Evidence')}
                    >
                      <FileText size={18} /> View All Associated Evidence
                    </button>
                  </div>
                )}
              </div>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="chat-container chat-container-with-sidebar">
          {/* ChatGPT-style Chats History Sidebar */}
          <div className="chat-history-sidebar">
            <div className="chat-history-sidebar-header">
              <button 
                type="button" 
                className="btn btn-primary btn-sm w-full flex items-center justify-center gap-1.5" 
                onClick={handleNewChat}
              >
                <Plus size={14} />
                <span>New Chat</span>
              </button>
            </div>

            {/* Search */}
            <div className="chat-history-search">
              <div className="input-with-icon">
                <Search size={13} className="input-icon" />
                <input
                  type="text"
                  className="input text-xs"
                  placeholder="Search chats..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>
            </div>

            {/* Session Folders List */}
            <div className="chat-history-list">
              {sessionsLoading ? (
                <div className="p-4 text-center text-xs text-gray-400">Loading history...</div>
              ) : (searchQuery ? sessions.filter(s => s.title.toLowerCase().includes(searchQuery.toLowerCase())) : sessions).length === 0 ? (
                <div className="p-6 text-center text-xs text-gray-400 flex flex-col items-center gap-2">
                  <FolderOpen size={24} className="text-gray-300" />
                  <span>No previous chats</span>
                  <span className="text-[10px] text-gray-400">Start asking questions to create your first session</span>
                </div>
              ) : (
                groupSessionsByDate(
                  searchQuery ? sessions.filter(s => s.title.toLowerCase().includes(searchQuery.toLowerCase())) : sessions
                ).map(([groupLabel, groupSessions]) => (
                  <div key={groupLabel} className="chat-sidebar-group">
                    <div className="chat-sidebar-group-label">{groupLabel}</div>
                    {groupSessions.map((s) => (
                      <div
                        key={s.session_id}
                        className={`chat-sidebar-item ${activeSessionId === s.session_id ? 'active' : ''}`}
                        onClick={() => handleSelectSession(s.session_id)}
                      >
                        {editingSessionId === s.session_id ? (
                          <div className="chat-sidebar-item-edit" onClick={(e) => e.stopPropagation()}>
                            <input
                              type="text"
                              className="input text-xs"
                              value={editTitle}
                              onChange={(e) => setEditTitle(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') handleSaveRename();
                                if (e.key === 'Escape') setEditingSessionId(null);
                              }}
                              autoFocus
                            />
                            <button className="btn btn-ghost btn-sm p-1" onClick={handleSaveRename}><Check size={12} /></button>
                            <button className="btn btn-ghost btn-sm p-1" onClick={() => setEditingSessionId(null)}><X size={12} /></button>
                          </div>
                        ) : (
                          <>
                            <MessageSquare size={13} className="chat-sidebar-item-icon" />
                            <div className="chat-sidebar-item-content">
                              <div className="chat-sidebar-item-title">{s.title}</div>
                            </div>
                            <div className="chat-sidebar-item-actions" onClick={(e) => e.stopPropagation()}>
                              <button
                                className="btn btn-ghost btn-sm p-1 text-gray-400 hover:text-gray-700"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setContextMenuSessionId(
                                    contextMenuSessionId === s.session_id ? null : s.session_id
                                  );
                                }}
                              >
                                <MoreHorizontal size={13} />
                              </button>
                              {contextMenuSessionId === s.session_id && (
                                <div className="chat-context-menu" onClick={(e) => e.stopPropagation()}>
                                  <button onClick={() => handleStartRename(s)}>
                                    <Edit3 size={11} /> Rename
                                  </button>
                                  <button className="danger" onClick={() => handleDeleteSession(s.session_id)}>
                                    <Trash2 size={11} /> Delete
                                  </button>
                                </div>
                              )}
                            </div>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Main Chat Panel */}
          <div className="chat-main-panel">
            <div className="p-3 bg-gray-50 border-b border-gray-200 flex justify-between items-center">
              <div className="flex items-center gap-2 min-w-0">
                <Bot size={18} className="text-primary-600 shrink-0" />
                <h2 className="font-semibold text-gray-800 text-sm truncate">
                  {sessions.find(s => s.session_id === activeSessionId)?.title || `Supplier Assistant — ${supplier.name}`}
                </h2>
                <span className="badge badge-info text-[10px] shrink-0">{supplier.id}</span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Link
                  to="/assistant"
                  className="btn btn-ghost btn-sm text-xs flex items-center gap-1 text-gray-600 hover:text-primary-600"
                  title="Open in dedicated full-page AI Assistant"
                >
                  <ExternalLink size={13} /> Fullscreen
                </Link>
                <button className="btn btn-ghost btn-sm text-xs" onClick={() => setChatOpen(false)}>
                  Close
                </button>
              </div>
            </div>
            
            <div className="chat-messages">
              {messagesLoading ? (
                <div className="loading-container py-12">
                  <div className="loading-spinner"></div>
                  <div className="loading-text">Loading conversation history...</div>
                </div>
              ) : (
                messages.map((msg, idx) => (
                  <div key={idx} className={`chat-message ${msg.role}`}>
                    <div className="chat-message-avatar">
                      {msg.role === 'assistant' ? <Bot size={16} /> : 'ME'}
                    </div>
                    <div>
                      <div className="chat-message-content" style={{ whiteSpace: 'pre-line' }}>
                        {msg.content}
                      </div>
                      
                      {msg.role === 'assistant' && (msg.keyFindings?.length > 0 || msg.evidence?.length > 0) && (
                        <div className="chat-message-findings mt-3 bg-white p-4 rounded-lg border border-gray-100 shadow-sm">
                          {msg.keyFindings?.length > 0 && (
                            <div className="mb-3">
                              <h4>Key Findings</h4>
                              <ul>
                                {msg.keyFindings.map((kf, i) => <li key={i}>{kf}</li>)}
                              </ul>
                            </div>
                          )}
                          
                          {msg.suggestedActions?.length > 0 && (
                            <div className="mb-3">
                              <h4>Suggested Actions</h4>
                              <div className="flex flex-wrap gap-2 mt-2">
                                {msg.suggestedActions.map((action, i) => (
                                  <button key={i} className="btn btn-secondary btn-sm bg-gray-50">{action}</button>
                                ))}
                              </div>
                            </div>
                          )}
                          
                          {msg.evidence?.length > 0 && (
                            <div className="mt-3 pt-3 border-t border-gray-100">
                              <button 
                                className="evidence-trigger"
                                onClick={() => openEvidence(msg.evidence, 'Supporting Evidence')}
                              >
                                View Evidence Sources
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                ))
              )}
              {isTyping && (
                <div className="chat-message assistant">
                  <div className="chat-message-avatar"><Bot size={16} /></div>
                  <div className="chat-message-content bg-gray-100 flex items-center gap-1 h-10">
                    <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></span>
                    <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></span>
                    <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.4s' }}></span>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
            
            <form className="chat-input-area" onSubmit={handleSendMessage}>
              <input 
                ref={inputRef}
                type="text" 
                className="input" 
                placeholder={`Ask about ${supplier.name}'s contracts, penalties, SLAs, pricing...`} 
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                disabled={isTyping}
              />
              <button 
                type="submit" 
                className="btn btn-primary"
                disabled={isTyping || !inputMessage.trim()}
              >
                <Send size={18} />
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
