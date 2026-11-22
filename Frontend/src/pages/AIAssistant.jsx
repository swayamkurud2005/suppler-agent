import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  MessageSquare, Send, Bot, Plus, Trash2, Edit3, Check, X,
  Clock, ChevronDown, ChevronRight, Users, Sparkles, Search,
  MoreHorizontal, FolderOpen
} from 'lucide-react';
import { EvidenceModal } from '../components/ui';
import {
  getChatSessions,
  createChatSession,
  getSessionMessages,
  sendSessionMessage,
  renameChatSession,
  deleteChatSession,
  getSuppliers,
} from '../services';

// Group sessions by time period (like ChatGPT)
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


export default function AIAssistant() {
  const navigate = useNavigate();
  const location = useLocation();

  // Session state
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [messagesLoading, setMessagesLoading] = useState(false);

  // Chat input
  const [inputMessage, setInputMessage] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Supplier selection for new chats
  const [suppliers, setSuppliers] = useState([]);
  const [selectedSupplier, setSelectedSupplier] = useState(null);
  const [showSupplierSelect, setShowSupplierSelect] = useState(false);

  // Sidebar state
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [editingSessionId, setEditingSessionId] = useState(null);
  const [editTitle, setEditTitle] = useState('');
  const [contextMenuSessionId, setContextMenuSessionId] = useState(null);

  // Evidence modal
  const [evidenceModalOpen, setEvidenceModalOpen] = useState(false);
  const [evidenceData, setEvidenceData] = useState([]);
  const [evidenceTitle, setEvidenceTitle] = useState('');

  // Load sessions and suppliers on mount
  useEffect(() => {
    loadSessions();
    loadSuppliers();
  }, []);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  // Close context menu on click outside
  useEffect(() => {
    const handler = () => setContextMenuSessionId(null);
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, []);

  const loadSessions = async () => {
    setSessionsLoading(true);
    try {
      const res = await getChatSessions();
      if (res.status === 'success' && res.data) {
        setSessions(res.data);
      }
    } catch (err) {
      console.error('Failed to load sessions:', err);
    } finally {
      setSessionsLoading(false);
    }
  };

  const loadSuppliers = async () => {
    try {
      const res = await getSuppliers();
      if (res.status === 'success' && res.data) {
        setSuppliers(res.data);
      }
    } catch (err) {
      console.error('Failed to load suppliers:', err);
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
        setMessages(loaded);
        // Set the supplier context from session
        if (res.data.session?.supplier_id) {
          const sup = suppliers.find(s => s.id === res.data.session.supplier_id);
          if (sup) setSelectedSupplier(sup);
        }
      }
    } catch (err) {
      console.error('Failed to load messages:', err);
    } finally {
      setMessagesLoading(false);
    }
  };

  const handleNewChat = () => {
    setActiveSessionId(null);
    setMessages([]);
    setSelectedSupplier(null);
    setShowSupplierSelect(true);
    setTimeout(() => inputRef.current?.focus(), 100);
  };

  const handleSelectSession = async (sessionId) => {
    setActiveSessionId(sessionId);
    setShowSupplierSelect(false);
    setContextMenuSessionId(null);
    await loadSessionMessages(sessionId);
  };

  const handleDeleteSession = async (sessionId) => {
    try {
      await deleteChatSession(sessionId);
      setSessions(prev => prev.filter(s => s.session_id !== sessionId));
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
        setMessages([]);
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

  const handleSendMessage = async (e) => {
    e.preventDefault();
    if (!inputMessage.trim() || isTyping) return;

    const userMsg = inputMessage.trim();
    if (!selectedSupplier?.id) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Select a supplier before asking a question. I will answer only from that supplier\'s contract.',
        timestamp: new Date().toISOString(),
      }]);
      setShowSupplierSelect(true);
      return;
    }
    setInputMessage('');

    // Add user message to UI immediately
    setMessages(prev => [...prev, {
      role: 'user',
      content: userMsg,
      timestamp: new Date().toISOString(),
    }]);

    setIsTyping(true);

    try {
      let sessionId = activeSessionId;

      // Create a new session if needed
      if (!sessionId) {
        const supplierId = selectedSupplier?.id || null;
        const supplierName = selectedSupplier?.name || null;
        const createRes = await createChatSession(supplierId, supplierName);
        if (createRes.status === 'success' && createRes.data) {
          sessionId = createRes.data.session_id;
          setActiveSessionId(sessionId);
          setSessions(prev => [createRes.data, ...prev]);
        } else {
          throw new Error('Failed to create chat session');
        }
      }

      // Send the message
      const res = await sendSessionMessage(sessionId, userMsg, selectedSupplier?.id);
      if (res.status === 'success' && res.data) {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: res.data.content,
          keyFindings: res.data.keyFindings || [],
          evidence: res.data.evidence || [],
          suggestedActions: res.data.suggestedActions || [],
          timestamp: res.data.timestamp,
        }]);

        // Update session title and supplier in sidebar
        if (res.data.session_title) {
          setSessions(prev =>
            prev.map(s =>
              s.session_id === sessionId
                ? {
                    ...s,
                    title: res.data.session_title,
                    supplier_id: res.data.supplier_id || s.supplier_id,
                    supplier_name: res.data.supplier_name || s.supplier_name,
                    updated_at: new Date().toISOString(),
                    message_count: (s.message_count || 0) + 2
                  }
                : s
            )
          );
        }

        // Sync selectedSupplier if resolved by backend
        if (res.data.supplier_id) {
          const matched = suppliers.find(s => s.id === res.data.supplier_id);
          if (matched && (!selectedSupplier || selectedSupplier.id !== matched.id)) {
            setSelectedSupplier(matched);
          }
        }
      }
    } catch (error) {
      console.error('Chat failed:', error);
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'I encountered an error while processing your request. Please try again.',
        timestamp: new Date().toISOString(),
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

  // Filter sessions by search
  const filteredSessions = searchQuery
    ? sessions.filter(s =>
        s.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (s.supplier_name || '').toLowerCase().includes(searchQuery.toLowerCase())
      )
    : sessions;

  const groupedSessions = groupSessionsByDate(filteredSessions);
  const activeSession = sessions.find(s => s.session_id === activeSessionId);

  return (
    <div className="ai-assistant-page">
      <EvidenceModal
        isOpen={evidenceModalOpen}
        onClose={() => setEvidenceModalOpen(false)}
        title={evidenceTitle}
        evidence={evidenceData}
      />

      {/* Chat History Sidebar */}
      <div className={`chat-sidebar ${sidebarOpen ? 'open' : 'collapsed'}`}>
        <div className="chat-sidebar-header">
          <button className="btn btn-primary btn-sm chat-new-btn" onClick={handleNewChat}>
            <Plus size={16} />
            <span>New Chat</span>
          </button>
        </div>

        {/* Search */}
        <div className="chat-sidebar-search">
          <div className="input-with-icon">
            <Search size={14} className="input-icon" />
            <input
              type="text"
              className="input"
              placeholder="Search chats..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>

        {/* Session List */}
        <div className="chat-sidebar-list">
          {sessionsLoading ? (
            <div className="loading-container" style={{ padding: '2rem' }}>
              <div className="loading-spinner" style={{ width: 24, height: 24 }}></div>
            </div>
          ) : filteredSessions.length === 0 ? (
            <div className="chat-sidebar-empty">
              <FolderOpen size={32} className="text-gray-300" />
              <p>No conversations yet</p>
              <p className="text-xs text-gray-400">Start a new chat to begin</p>
            </div>
          ) : (
            groupedSessions.map(([groupLabel, groupSessions]) => (
              <div key={groupLabel} className="chat-sidebar-group">
                <div className="chat-sidebar-group-label">{groupLabel}</div>
                {groupSessions.map(session => (
                  <div
                    key={session.session_id}
                    className={`chat-sidebar-item ${activeSessionId === session.session_id ? 'active' : ''}`}
                    onClick={() => handleSelectSession(session.session_id)}
                  >
                    {editingSessionId === session.session_id ? (
                      <div className="chat-sidebar-item-edit" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="text"
                          className="input"
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter') handleSaveRename(); if (e.key === 'Escape') setEditingSessionId(null); }}
                          autoFocus
                        />
                        <button className="btn btn-ghost btn-sm" onClick={handleSaveRename}><Check size={14} /></button>
                        <button className="btn btn-ghost btn-sm" onClick={() => setEditingSessionId(null)}><X size={14} /></button>
                      </div>
                    ) : (
                      <>
                        <MessageSquare size={14} className="chat-sidebar-item-icon" />
                        <div className="chat-sidebar-item-content">
                          <div className="chat-sidebar-item-title">{session.title}</div>
                          {session.supplier_name && (
                            <div className="chat-sidebar-item-supplier">
                              <Users size={10} /> {session.supplier_name}
                            </div>
                          )}
                        </div>
                        <div className="chat-sidebar-item-actions" onClick={(e) => e.stopPropagation()}>
                          <button
                            className="btn btn-ghost btn-sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              setContextMenuSessionId(
                                contextMenuSessionId === session.session_id ? null : session.session_id
                              );
                            }}
                          >
                            <MoreHorizontal size={14} />
                          </button>
                          {contextMenuSessionId === session.session_id && (
                            <div className="chat-context-menu" onClick={(e) => e.stopPropagation()}>
                              <button onClick={() => handleStartRename(session)}>
                                <Edit3 size={12} /> Rename
                              </button>
                              <button className="danger" onClick={() => handleDeleteSession(session.session_id)}>
                                <Trash2 size={12} /> Delete
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

      {/* Main Chat Area */}
      <div className="chat-main-area">
        {/* Chat Header */}
        <div className="chat-main-header">
          <div className="flex items-center gap-2">
            <Bot size={20} className="text-primary-600" />
            <h2 className="font-semibold text-gray-800">
              {activeSession ? activeSession.title : 'Supplier AI Assistant'}
            </h2>
            {(activeSession?.supplier_name || selectedSupplier?.name) && (
              <span className="badge badge-info flex items-center gap-1">
                <Users size={12} /> {activeSession?.supplier_name || selectedSupplier?.name}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500 font-medium">Context:</span>
            <select
              className="select select-sm text-xs"
              style={{ minWidth: '160px', padding: '0.25rem 0.5rem', height: '32px' }}
              value={selectedSupplier?.id || ''}
              onChange={(e) => {
                const sup = suppliers.find(s => s.id === e.target.value);
                setSelectedSupplier(sup || null);
              }}
              title="Active supplier for analysis"
            >
              {suppliers.map(s => (
                <option key={s.id} value={s.id}>{s.name} ({s.id})</option>
              ))}
            </select>
          </div>
        </div>

        {/* Messages Area */}
        <div className="chat-main-messages">
          {!activeSessionId && messages.length === 0 ? (
            /* Welcome / New Chat Screen */
            <div className="chat-welcome">
              <div className="chat-welcome-icon">
                <Sparkles size={40} />
              </div>
              <h2>Supplier 360 AI Assistant</h2>
              <p>Ask questions about your suppliers, contracts, performance, pricing, and more.</p>

              {/* Supplier selector for new chat */}
              <div className="chat-supplier-selector">
                  <label>Select the supplier contract to search:</label>
                <select
                  className="select"
                  value={selectedSupplier?.id || ''}
                  onChange={(e) => {
                    const sup = suppliers.find(s => s.id === e.target.value);
                    setSelectedSupplier(sup || null);
                  }}
                >
                  <option value="">Select a supplier</option>
                  {suppliers.map(s => (
                    <option key={s.id} value={s.id}>{s.name} ({s.id})</option>
                  ))}
                </select>
              </div>

              {/* Quick start suggestions */}
              <div className="chat-suggestions">
                {[
                  'What are the payment terms for this supplier?',
                  'Analyze contract penalty clauses',
                  'What is the delivery SLA?',
                  'Compare pricing against market benchmarks',
                ].map((suggestion, i) => (
                  <button
                    key={i}
                    className="chat-suggestion-chip"
                    onClick={() => {
                      setInputMessage(suggestion);
                      inputRef.current?.focus();
                    }}
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          ) : messagesLoading ? (
            <div className="loading-container py-20">
              <div className="loading-spinner"></div>
              <div className="loading-text">Loading conversation...</div>
            </div>
          ) : (
            /* Message Thread */
            <>
              {messages.map((msg, idx) => (
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
              ))}
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
            </>
          )}
        </div>

        {/* Chat Input */}
        <form className="chat-input-area" onSubmit={handleSendMessage}>
          {!activeSessionId && showSupplierSelect && (
            <select
              className="select chat-input-supplier-select"
              value={selectedSupplier?.id || ''}
              onChange={(e) => {
                const sup = suppliers.find(s => s.id === e.target.value);
                setSelectedSupplier(sup || null);
              }}
              style={{ width: 'auto', minWidth: 160, flexShrink: 0 }}
            >
              <option value="">Select supplier</option>
              {suppliers.map(s => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          )}
          <input
            ref={inputRef}
            type="text"
            className="input"
            placeholder="Ask about your suppliers, contracts, or performance..."
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
  );
}
