import { useState, useEffect, useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Search,
  Filter,
  ChevronRight,
  AlertTriangle,
  Plus,
  Trash2,
  LayoutGrid,
  Table as TableIcon,
  Sparkles,
  ExternalLink,
} from 'lucide-react';
import { StatusBadge } from '../components/ui';
import AddSupplierModal from '../components/AddSupplierModal';
import { getSuppliers, getSupplierCategories, deleteSupplier } from '../services';

const RISK_COLORS = {
  low: '#10B981',
  moderate: '#F59E0B',
  high: '#EF4444',
};

export default function SuppliersList() {
  const navigate = useNavigate();
  const [suppliers, setSuppliers] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');

  const [viewMode, setViewMode] = useState('grid'); // 'grid' | 'table'
  const [riskTierFilter, setRiskTierFilter] = useState(null);
  const [renewalFilter, setRenewalFilter] = useState(false);
  const [sortField, setSortField] = useState('riskScore');
  const [sortOrder, setSortOrder] = useState('desc'); // 'desc' | 'asc'

  // Add Supplier Modal state
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);

  const loadData = async () => {
    setLoading(true);
    try {
      const [suppRes, catRes] = await Promise.all([
        getSuppliers({ search: searchTerm, status: statusFilter, category: categoryFilter }),
        getSupplierCategories(),
      ]);

      if (suppRes.status === 'success') setSuppliers(suppRes.data);
      if (catRes.status === 'success') setCategories(catRes.data);
    } catch (error) {
      console.error('Failed to load suppliers:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData();
    }, 300);
    return () => clearTimeout(timer);
  }, [searchTerm, statusFilter, categoryFilter]);

  const handleOpenAddModal = () => {
    setIsAddModalOpen(true);
  };

  const handleCloseAddModal = () => {
    setIsAddModalOpen(false);
  };

  const handleDelete = async (event, supplier) => {
    event.preventDefault();
    event.stopPropagation();
    if (
      !window.confirm(
        `Delete ${supplier.name}? This permanently removes its contracts, orders, quality records, and indexed contract chunks.`
      )
    )
      return;
    const result = await deleteSupplier(supplier.id);
    if (result?.status === 'success') setSuppliers((current) => current.filter((item) => item.id !== supplier.id));
    else window.alert(result?.message || 'Supplier could not be deleted.');
  };

  // ────────────────────────────────────────────────────────────
  // Portfolio Analytics Computations (for Graphs & KPIs)
  // ────────────────────────────────────────────────────────────
  const portfolioStats = useMemo(() => {
    if (!suppliers.length) {
      return {
        total: 0,
        activeCount: 0,
        underReviewCount: 0,
        avgRisk: 0,
        highRiskCount: 0,
        expiringSoonCount: 0,
      };
    }

    const total = suppliers.length;
    const activeCount = suppliers.filter((s) => s.status === 'active').length;
    const underReviewCount = suppliers.filter((s) => s.status === 'under_review').length;
    const totalRisk = suppliers.reduce((sum, s) => sum + (s.riskScore || 0), 0);
    const avgRisk = Math.round(totalRisk / total);
    const highRiskCount = suppliers.filter((s) => (s.riskScore || 0) > 60).length;

    // Upcoming renewals within 90 days
    const now = new Date();
    const in90Days = new Date(now.getTime() + 90 * 24 * 60 * 60 * 1000);
    const expiringSoonCount = suppliers.filter((s) => {
      if (!s.renewalDate) return false;
      const r = new Date(s.renewalDate);
      return r >= now && r <= in90Days;
    }).length;

    return {
      total,
      activeCount,
      underReviewCount,
      avgRisk,
      highRiskCount,
      expiringSoonCount,
    };
  }, [suppliers]);

  // Graph 1: Risk Distribution Data
  const riskDistributionData = useMemo(() => {
    let low = 0;
    let moderate = 0;
    let high = 0;

    suppliers.forEach((s) => {
      const score = s.riskScore || 0;
      if (score <= 40) low++;
      else if (score <= 70) moderate++;
      else high++;
    });

    return [
      {
        tier: 'Low Risk',
        key: 'low',
        range: '0 – 40',
        count: low,
        fill: RISK_COLORS.low,
      },
      {
        tier: 'Moderate',
        key: 'moderate',
        range: '41 – 70',
        count: moderate,
        fill: RISK_COLORS.moderate,
      },
      {
        tier: 'High Risk',
        key: 'high',
        range: '71 – 100',
        count: high,
        fill: RISK_COLORS.high,
      },
    ];
  }, [suppliers]);

  // Graph 2: Category Breakdown with Avg Risk
  const categoryChartData = useMemo(() => {
    const map = {};
    suppliers.forEach((s) => {
      const cat = s.category || 'General';
      if (!map[cat]) {
        map[cat] = { category: cat, count: 0, totalRisk: 0 };
      }
      map[cat].count += 1;
      map[cat].totalRisk += s.riskScore || 0;
    });

    return Object.values(map)
      .map((item) => ({
        ...item,
        avgRisk: Math.round(item.totalRisk / item.count),
      }))
      .sort((a, b) => b.count - a.count);
  }, [suppliers]);

  // Graph 3: Top At-Risk Suppliers Comparison
  const topRiskSuppliersData = useMemo(() => {
    return [...suppliers]
      .sort((a, b) => (b.riskScore || 0) - (a.riskScore || 0))
      .slice(0, 6)
      .map((s) => ({
        id: s.id,
        name: s.name.length > 18 ? s.name.slice(0, 16) + '…' : s.name,
        fullName: s.name,
        riskScore: s.riskScore || 0,
        category: s.category,
        fill: (s.riskScore || 0) > 70 ? RISK_COLORS.high : RISK_COLORS.moderate,
      }));
  }, [suppliers]);

  // Graph 4: Partnership Longevity (Donut)
  const longevityData = useMemo(() => {
    let newSuppliers = 0;       // <= 1 yr
    let established = 0;       // 2 - 4 yrs
    let strategicPartners = 0; // 5+ yrs

    suppliers.forEach((s) => {
      const yrs = s.relationshipYears || 1;
      if (yrs <= 1) newSuppliers++;
      else if (yrs <= 4) established++;
      else strategicPartners++;
    });

    return [
      { name: 'New (≤ 1 Year)', value: newSuppliers, color: '#06B6D4' },
      { name: 'Established (2-4 Yrs)', value: established, color: '#4F46E5' },
      { name: 'Strategic (5+ Yrs)', value: strategicPartners, color: '#10B981' },
    ].filter((item) => item.value > 0);
  }, [suppliers]);

  // ────────────────────────────────────────────────────────────
  // Filtered and Sorted Suppliers for Display
  // ────────────────────────────────────────────────────────────
  const displayedSuppliers = useMemo(() => {
    let list = [...suppliers];

    // Chart-driven Risk Tier Filter
    if (riskTierFilter === 'low') {
      list = list.filter((s) => (s.riskScore || 0) <= 40);
    } else if (riskTierFilter === 'moderate') {
      list = list.filter((s) => (s.riskScore || 0) > 40 && (s.riskScore || 0) <= 70);
    } else if (riskTierFilter === 'high') {
      list = list.filter((s) => (s.riskScore || 0) > 70);
    }

    // Renewal Filter
    if (renewalFilter) {
      const now = new Date();
      const in90Days = new Date(now.getTime() + 90 * 24 * 60 * 60 * 1000);
      list = list.filter((s) => {
        if (!s.renewalDate) return false;
        const r = new Date(s.renewalDate);
        return r >= now && r <= in90Days;
      });
    }

    // Sorting
    list.sort((a, b) => {
      let aVal = a[sortField];
      let bVal = b[sortField];
      if (typeof aVal === 'string') aVal = aVal.toLowerCase();
      if (typeof bVal === 'string') bVal = bVal.toLowerCase();
      if (aVal < bVal) return sortOrder === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortOrder === 'asc' ? 1 : -1;
      return 0;
    });

    return list;
  }, [suppliers, riskTierFilter, renewalFilter, sortField, sortOrder]);

  const handleSort = (field) => {
    if (sortField === field) {
      setSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortOrder('desc');
    }
  };

  return (
    <div className="animate-fade-in space-y-6">
      {/* ────────────────────────────────────────────────────────────
          PAGE HEADER
          ──────────────────────────────────────────────────────────── */}
      <div className="page-header flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="page-title">Suppliers</h1>
            <span className="badge badge-info text-xs flex items-center gap-1">
              <Sparkles size={12} /> Portfolio Intelligence
            </span>
          </div>
          <p className="page-subtitle">
            Manage, benchmark, and take proactive insights across your supplier network
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            className="btn btn-primary btn-sm flex items-center gap-2 shadow-sm"
            onClick={handleOpenAddModal}
          >
            <Plus size={16} /> Add Supplier
          </button>
        </div>
      </div>

      {/* ────────────────────────────────────────────────────────────
          VISUAL INSIGHTS & ANALYTICS SECTION
          ──────────────────────────────────────────────────────────── */}
      {false && (
        <div className="space-y-4 animate-fade-in">
          {/* Executive KPI Summary Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* Total Suppliers */}
            <div className="card border-l-4 border-l-primary-500 shadow-xs">
              <div className="card-body p-4 flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Total Network
                  </p>
                  <p className="text-2xl font-bold text-gray-900 mt-0.5">
                    {portfolioStats.total}
                  </p>
                  <p className="text-[11px] text-gray-500 mt-1">
                    {portfolioStats.activeCount} Active • {portfolioStats.underReviewCount} Under Review
                  </p>
                </div>
                <div className="w-10 h-10 rounded-xl bg-primary-50 text-primary-600 flex items-center justify-center">
                  <Users size={20} />
                </div>
              </div>
            </div>

            {/* Average Risk Score */}
            <div
              className={`card border-l-4 shadow-xs ${
                portfolioStats.avgRisk > 60
                  ? 'border-l-red-500'
                  : portfolioStats.avgRisk > 40
                  ? 'border-l-amber-500'
                  : 'border-l-emerald-500'
              }`}
            >
              <div className="card-body p-4 flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Portfolio Avg Risk
                  </p>
                  <div className="flex items-baseline gap-1.5 mt-0.5">
                    <span className="text-2xl font-bold text-gray-900">
                      {portfolioStats.avgRisk}
                    </span>
                    <span className="text-xs text-gray-400">/ 100</span>
                  </div>
                  <span
                    className={`inline-block mt-1 text-[11px] font-medium px-2 py-0.5 rounded-full ${
                      portfolioStats.avgRisk > 60
                        ? 'bg-red-50 text-red-700'
                        : portfolioStats.avgRisk > 40
                        ? 'bg-amber-50 text-amber-700'
                        : 'bg-emerald-50 text-emerald-700'
                    }`}
                  >
                    {portfolioStats.avgRisk > 60
                      ? 'Elevated Risk'
                      : portfolioStats.avgRisk > 40
                      ? 'Moderate Health'
                      : 'Healthy Portfolio'}
                  </span>
                </div>
                <div
                  className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                    portfolioStats.avgRisk > 60
                      ? 'bg-red-50 text-red-600'
                      : 'bg-emerald-50 text-emerald-600'
                  }`}
                >
                  <ShieldCheck size={20} />
                </div>
              </div>
            </div>

            {/* High Risk Suppliers Alert */}
            <div
              className={`card border-l-4 shadow-xs cursor-pointer transition-all hover:shadow-md ${
                riskTierFilter === 'high'
                  ? 'ring-2 ring-red-500 bg-red-50/20'
                  : 'border-l-red-500'
              }`}
              onClick={() => setRiskTierFilter((prev) => (prev === 'high' ? null : 'high'))}
              title="Click to filter high risk suppliers"
            >
              <div className="card-body p-4 flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider flex items-center gap-1">
                    Attention Required
                  </p>
                  <p className="text-2xl font-bold text-red-600 mt-0.5">
                    {portfolioStats.highRiskCount}
                  </p>
                  <p className="text-[11px] text-red-700 font-medium mt-1 flex items-center gap-1">
                    <span>Score &gt; 60</span> • {riskTierFilter === 'high' ? 'Filtering Active' : 'Click to filter'}
                  </p>
                </div>
                <div className="w-10 h-10 rounded-xl bg-red-50 text-red-600 flex items-center justify-center">
                  <ShieldAlert size={20} />
                </div>
              </div>
            </div>

            {/* Upcoming Renewals */}
            <div
              className={`card border-l-4 shadow-xs cursor-pointer transition-all hover:shadow-md ${
                renewalFilter ? 'ring-2 ring-amber-500 bg-amber-50/20' : 'border-l-amber-500'
              }`}
              onClick={() => setRenewalFilter((prev) => !prev)}
              title="Click to filter contracts expiring in 90 days"
            >
              <div className="card-body p-4 flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Renewals in 90 Days
                  </p>
                  <p className="text-2xl font-bold text-amber-600 mt-0.5">
                    {portfolioStats.expiringSoonCount}
                  </p>
                  <p className="text-[11px] text-amber-700 font-medium mt-1">
                    {renewalFilter ? 'Filtering Active' : 'Click to filter'}
                  </p>
                </div>
                <div className="w-10 h-10 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center">
                  <Calendar size={20} />
                </div>
              </div>
            </div>
          </div>

          {/* Interactive Charts Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Chart 1: Risk Distribution Spectrum */}
            <div className="card">
              <div className="card-header pb-2 flex items-center justify-between">
                <div>
                  <h3 className="card-title text-sm font-bold text-gray-900 flex items-center gap-2">
                    <ShieldAlert size={16} className="text-primary-600" />
                    Supplier Risk Distribution Spectrum
                  </h3>
                  <p className="text-[11px] text-gray-500">
                    Click any risk bar to instantly filter the list below
                  </p>
                </div>
                {riskTierFilter && (
                  <button
                    type="button"
                    onClick={() => setRiskTierFilter(null)}
                    className="text-[11px] font-semibold text-primary-600 hover:text-primary-800 bg-primary-50 px-2 py-0.5 rounded-md"
                  >
                    Reset Filter
                  </button>
                )}
              </div>
              <div className="card-body pt-0">
                <div className="h-56 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={riskDistributionData}
                      margin={{ top: 15, right: 20, left: -10, bottom: 5 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F3F4F6" />
                      <XAxis
                        dataKey="tier"
                        tick={{ fontSize: 11, fill: '#4B5563', fontWeight: 600 }}
                      />
                      <YAxis
                        allowDecimals={false}
                        tick={{ fontSize: 11, fill: '#6B7280' }}
                      />
                      <Tooltip
                        cursor={{ fill: 'rgba(0, 0, 0, 0.04)' }}
                        content={({ active, payload }) => {
                          if (!active || !payload?.length) return null;
                          const data = payload[0].payload;
                          const pct = portfolioStats.total > 0 ? Math.round((data.count / portfolioStats.total) * 100) : 0;
                          return (
                            <div className="bg-white p-2.5 rounded-lg shadow-md border border-gray-200 text-xs">
                              <p className="font-bold text-gray-900">{data.tier} ({data.range})</p>
                              <p className="text-primary-700 font-semibold mt-1">
                                {data.count} Suppliers ({pct}% of portfolio)
                              </p>
                              <p className="text-[10px] text-gray-500 mt-0.5 italic">
                                Click bar to filter
                              </p>
                            </div>
                          );
                        }}
                      />
                      <Bar
                        dataKey="count"
                        radius={[6, 6, 0, 0]}
                        cursor="pointer"
                        onClick={(entry) => {
                          setRiskTierFilter((prev) => (prev === entry.key ? null : entry.key));
                        }}
                      >
                        {riskDistributionData.map((entry, index) => (
                          <Cell
                            key={`cell-${index}`}
                            fill={entry.fill}
                            opacity={riskTierFilter && riskTierFilter !== entry.key ? 0.35 : 1}
                            stroke={riskTierFilter === entry.key ? '#1E293B' : 'transparent'}
                            strokeWidth={riskTierFilter === entry.key ? 2 : 0}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>

            {/* Chart 2: Category Breakdown with Risk Profile */}
            <div className="card">
              <div className="card-header pb-2 flex items-center justify-between">
                <div>
                  <h3 className="card-title text-sm font-bold text-gray-900 flex items-center gap-2">
                    <Building2 size={16} className="text-primary-600" />
                    Supplier Count & Avg Risk by Category
                  </h3>
                  <p className="text-[11px] text-gray-500">
                    Distribution across procurement material categories
                  </p>
                </div>
                {categoryFilter && (
                  <button
                    type="button"
                    onClick={() => setCategoryFilter('')}
                    className="text-[11px] font-semibold text-primary-600 hover:text-primary-800 bg-primary-50 px-2 py-0.5 rounded-md"
                  >
                    Clear Filter
                  </button>
                )}
              </div>
              <div className="card-body pt-0">
                <div className="h-56 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={categoryChartData}
                      layout="vertical"
                      margin={{ top: 10, right: 30, left: 30, bottom: 5 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#F3F4F6" />
                      <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
                      <YAxis
                        dataKey="category"
                        type="category"
                        tick={{ fontSize: 10, fill: '#374151', fontWeight: 500 }}
                        width={95}
                      />
                      <Tooltip
                        cursor={{ fill: 'rgba(0, 0, 0, 0.04)' }}
                        content={({ active, payload }) => {
                          if (!active || !payload?.length) return null;
                          const data = payload[0].payload;
                          return (
                            <div className="bg-white p-2.5 rounded-lg shadow-md border border-gray-200 text-xs">
                              <p className="font-bold text-gray-900">{data.category}</p>
                              <p className="text-gray-700 mt-1">
                                Suppliers: <strong>{data.count}</strong>
                              </p>
                              <p className="text-gray-700">
                                Avg Risk Score: <strong>{data.avgRisk}/100</strong>
                              </p>
                              <p className="text-[10px] text-gray-500 mt-0.5 italic">
                                Click bar to filter
                              </p>
                            </div>
                          );
                        }}
                      />
                      <Bar
                        dataKey="count"
                        fill="#4F46E5"
                        radius={[0, 4, 4, 0]}
                        cursor="pointer"
                        onClick={(entry) => {
                          setCategoryFilter((prev) => (prev === entry.category ? '' : entry.category));
                        }}
                      >
                        {categoryChartData.map((entry, idx) => (
                          <Cell
                            key={idx}
                            fill={categoryFilter === entry.category ? '#312E81' : PIE_COLORS[idx % PIE_COLORS.length]}
                            opacity={categoryFilter && categoryFilter !== entry.category ? 0.35 : 1}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>

            {/* Chart 3: Top At-Risk Suppliers Needing Action */}
            <div className="card">
              <div className="card-header pb-2 flex items-center justify-between">
                <div>
                  <h3 className="card-title text-sm font-bold text-gray-900 flex items-center gap-2">
                    <AlertTriangle size={16} className="text-red-500" />
                    Top At-Risk Suppliers
                  </h3>
                  <p className="text-[11px] text-gray-500">
                    Highest risk scores requiring contract or performance review
                  </p>
                </div>
                <span className="text-[11px] text-red-600 bg-red-50 px-2 py-0.5 rounded-full font-medium">
                  Attention Threshold: 60+
                </span>
              </div>
              <div className="card-body pt-0">
                <div className="h-56 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={topRiskSuppliersData}
                      layout="vertical"
                      margin={{ top: 10, right: 30, left: 30, bottom: 5 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#F3F4F6" />
                      <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11 }} />
                      <YAxis
                        dataKey="name"
                        type="category"
                        tick={{ fontSize: 10, fill: '#374151', fontWeight: 500 }}
                        width={110}
                      />
                      <Tooltip
                        content={({ active, payload }) => {
                          if (!active || !payload?.length) return null;
                          const data = payload[0].payload;
                          return (
                            <div className="bg-white p-2.5 rounded-lg shadow-md border border-gray-200 text-xs">
                              <p className="font-bold text-gray-900">{data.fullName}</p>
                              <p className="text-gray-500 text-[11px]">{data.category}</p>
                              <p className="text-red-600 font-bold mt-1">
                                Risk Score: {data.riskScore}/100
                              </p>
                              <p className="text-[10px] text-primary-600 mt-1">
                                Click to inspect Supplier 360 →
                              </p>
                            </div>
                          );
                        }}
                      />
                      <ReferenceLine
                        x={60}
                        stroke="#EF4444"
                        strokeDasharray="3 3"
                        label={{
                          value: 'Threshold (60)',
                          fill: '#EF4444',
                          fontSize: 10,
                          position: 'insideTopRight',
                        }}
                      />
                      <Bar
                        dataKey="riskScore"
                        radius={[0, 4, 4, 0]}
                        cursor="pointer"
                        onClick={(entry) => {
                          if (entry?.id) navigate(`/suppliers/${entry.id}/overview`);
                        }}
                      >
                        {topRiskSuppliersData.map((entry, index) => (
                          <Cell key={index} fill={entry.fill} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>

            {/* Chart 4: Partnership Longevity & Relationship Distribution */}
            <div className="card">
              <div className="card-header pb-2 flex items-center justify-between">
                <div>
                  <h3 className="card-title text-sm font-bold text-gray-900 flex items-center gap-2">
                    <Clock size={16} className="text-primary-600" />
                    Partnership Longevity
                  </h3>
                  <p className="text-[11px] text-gray-500">
                    Relationship tenure across supplier network
                  </p>
                </div>
              </div>
              <div className="card-body pt-0">
                <div className="h-56 w-full flex items-center justify-center">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={longevityData}
                        dataKey="value"
                        nameKey="name"
                        cx="50%"
                        cy="50%"
                        innerRadius={45}
                        outerRadius={75}
                        paddingAngle={3}
                      >
                        {longevityData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip
                        content={({ active, payload }) => {
                          if (!active || !payload?.length) return null;
                          const data = payload[0].payload;
                          const pct = portfolioStats.total > 0 ? Math.round((data.value / portfolioStats.total) * 100) : 0;
                          return (
                            <div className="bg-white p-2 rounded-lg shadow-md border border-gray-200 text-xs">
                              <p className="font-bold text-gray-800">{data.name}</p>
                              <p className="text-primary-600 font-semibold mt-0.5">
                                {data.value} Suppliers ({pct}%)
                              </p>
                            </div>
                          );
                        }}
                      />
                      <Legend
                        verticalAlign="bottom"
                        iconType="circle"
                        iconSize={8}
                        wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ────────────────────────────────────────────────────────────
          ACTIVE FILTER NOTIFICATION PILL
          ──────────────────────────────────────────────────────────── */}
      {false && (
        <div className="p-3 bg-indigo-50 border border-indigo-200 rounded-xl flex items-center justify-between gap-3 text-xs text-indigo-900 animate-fade-in">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-primary-700 flex items-center gap-1">
              <Filter size={13} /> Active Chart Filter:
            </span>
            {riskTierFilter && (
              <span className="badge badge-info bg-white text-indigo-800 border border-indigo-200">
                Risk Tier: <strong className="ml-1 capitalize">{riskTierFilter} Risk</strong>
              </span>
            )}
            {renewalFilter && (
              <span className="badge badge-warning bg-white text-amber-800 border border-amber-200">
                Expiring within 90 days
              </span>
            )}
            {categoryFilter && (
              <span className="badge badge-info bg-white text-indigo-800 border border-indigo-200">
                Category: <strong className="ml-1">{categoryFilter}</strong>
              </span>
            )}
            <span className="text-gray-500 font-medium">
              (Showing {displayedSuppliers.length} of {suppliers.length} suppliers)
            </span>
          </div>

          <button
            type="button"
            className="text-xs text-red-600 hover:text-red-800 font-semibold flex items-center gap-1 shrink-0"
            onClick={() => {
              setRiskTierFilter(null);
              setRenewalFilter(false);
              setCategoryFilter('');
            }}
          >
            <X size={13} /> Clear Filters
          </button>
        </div>
      )}

      {/* ────────────────────────────────────────────────────────────
          SEARCH & FILTER TOOLBAR
          ──────────────────────────────────────────────────────────── */}
      <div className="card">
        <div className="card-body p-4">
          <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-4">
            <div className="input-with-icon flex-1">
              <Search className="input-icon" size={18} />
              <input
                type="text"
                className="input"
                placeholder="Search suppliers by name, category, or location..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
            </div>

            <div className="flex items-center gap-3">
              <select
                className="select"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                <option value="">All Statuses</option>
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
                <option value="under_review">Under Review</option>
              </select>

              <select
                className="select"
                value={categoryFilter}
                onChange={(e) => setCategoryFilter(e.target.value)}
              >
                <option value="">All Categories</option>
                {categories.map((cat) => (
                  <option key={cat} value={cat}>
                    {cat}
                  </option>
                ))}
              </select>

              {/* View Switcher: Grid vs Table */}
              <div className="flex items-center border border-gray-200 rounded-lg p-0.5 bg-gray-50 shrink-0">
                <button
                  type="button"
                  className={`p-1.5 rounded-md transition-colors ${
                    viewMode === 'grid'
                      ? 'bg-white shadow-xs text-primary-600'
                      : 'text-gray-400 hover:text-gray-600'
                  }`}
                  onClick={() => setViewMode('grid')}
                  title="Grid View"
                >
                  <LayoutGrid size={16} />
                </button>
                <button
                  type="button"
                  className={`p-1.5 rounded-md transition-colors ${
                    viewMode === 'table'
                      ? 'bg-white shadow-xs text-primary-600'
                      : 'text-gray-400 hover:text-gray-600'
                  }`}
                  onClick={() => setViewMode('table')}
                  title="Table View"
                >
                  <TableIcon size={16} />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ────────────────────────────────────────────────────────────
          SUPPLIERS LIST / TABLE DISPLAY
          ──────────────────────────────────────────────────────────── */}
      {loading ? (
        <div className="loading-container py-20">
          <div className="loading-spinner"></div>
          <div className="loading-text">Loading suppliers...</div>
        </div>
      ) : displayedSuppliers.length === 0 ? (
        <div className="empty-state card">
          <Search size={48} className="empty-state-icon" />
          <div className="empty-state-title">No suppliers found</div>
          <div className="empty-state-description">
            Try adjusting your search or active filters to find what you're looking for.
          </div>
          <button
            className="btn btn-secondary mt-4"
            onClick={() => {
              setSearchTerm('');
              setStatusFilter('');
              setCategoryFilter('');
              setRiskTierFilter(null);
              setRenewalFilter(false);
            }}
          >
            Clear All Filters
          </button>
        </div>
      ) : viewMode === 'table' ? (
        /* TABLE VIEW */
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-gray-700">
              <thead className="bg-gray-50 border-b border-gray-200 uppercase text-[10px] tracking-wider text-gray-500 font-semibold">
                <tr>
                  <th
                    className="p-3 cursor-pointer hover:text-primary-700"
                    onClick={() => handleSort('name')}
                  >
                    Supplier Name
                  </th>
                  <th
                    className="p-3 cursor-pointer hover:text-primary-700"
                    onClick={() => handleSort('category')}
                  >
                    Category
                  </th>
                  <th className="p-3">Location</th>
                  <th
                    className="p-3 text-center cursor-pointer hover:text-primary-700"
                    onClick={() => handleSort('riskScore')}
                  >
                    Risk Score
                  </th>
                  <th className="p-3 text-center">Relationship</th>
                  <th className="p-3 text-center">Renewal Date</th>
                  <th className="p-3 text-center">Status</th>
                  <th className="p-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {displayedSuppliers.map((supplier) => (
                  <tr key={supplier.id} className="hover:bg-gray-50/70 transition-colors">
                    <td className="p-3 font-semibold text-gray-900">
                      <Link
                        to={`/suppliers/${supplier.id}/overview`}
                        className="text-primary-700 hover:text-primary-900 flex items-center gap-1.5"
                      >
                        {supplier.name}
                        {supplier.riskScore > 60 && (
                          <AlertTriangle size={13} className="text-amber-500" title="High Risk" />
                        )}
                      </Link>
                      <span className="text-[10px] font-mono text-gray-400 block">
                        {supplier.id}
                      </span>
                    </td>
                    <td className="p-3">{supplier.category}</td>
                    <td className="p-3 text-gray-600">{supplier.location}</td>
                    <td className="p-3 text-center">
                      <span
                        className={`inline-block px-2 py-0.5 rounded-full font-bold text-[11px] ${
                          supplier.riskScore > 70
                            ? 'bg-red-100 text-red-700'
                            : supplier.riskScore > 40
                            ? 'bg-amber-100 text-amber-700'
                            : 'bg-emerald-100 text-emerald-700'
                        }`}
                      >
                        {supplier.riskScore}/100
                      </span>
                    </td>
                    <td className="p-3 text-center">{supplier.relationshipYears} Years</td>
                    <td className="p-3 text-center text-gray-600">
                      {supplier.renewalDate
                        ? new Date(supplier.renewalDate).toLocaleDateString('en-GB', {
                            day: 'numeric',
                            month: 'short',
                            year: 'numeric',
                          })
                        : 'No contract'}
                    </td>
                    <td className="p-3 text-center">
                      <StatusBadge status={supplier.status} />
                    </td>
                    <td className="p-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Link
                          to={`/suppliers/${supplier.id}/overview`}
                          className="btn btn-secondary btn-sm p-1.5 text-primary-600 hover:bg-primary-50"
                          title="View Supplier 360"
                        >
                          <ChevronRight size={15} />
                        </Link>
                        <button
                          type="button"
                          onClick={(e) => handleDelete(e, supplier)}
                          className="btn btn-secondary btn-sm p-1.5 text-red-600 hover:bg-red-50"
                          title="Delete Supplier"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        /* GRID VIEW */
        <div className="supplier-card-grid">
          {displayedSuppliers.map((supplier) => (
            <Link
              to={`/suppliers/${supplier.id}/overview`}
              key={supplier.id}
              className="supplier-card hover:shadow-lg transition-all"
            >
              <div className="supplier-card-header">
                <div>
                  <div className="supplier-card-name flex items-center gap-2">
                    {supplier.name}
                    {supplier.riskScore > 60 && (
                      <AlertTriangle
                        size={16}
                        className="text-amber-500"
                        title="High Risk / Attention Required"
                      />
                    )}
                  </div>
                  <div className="supplier-card-category">
                    {supplier.category} • {supplier.location}
                  </div>
                </div>
                <StatusBadge status={supplier.status} />
              </div>

              <div className="text-sm text-gray-500 mt-2 mb-4">
                Primary Contact: {supplier.contactPerson || 'Not specified'}
              </div>

              <div className="supplier-card-metrics">
                <div className="supplier-metric">
                  <span className="supplier-metric-label">Relationship</span>
                  <span className="supplier-metric-value">{supplier.relationshipYears} Years</span>
                </div>
                <div className="supplier-metric">
                  <span className="supplier-metric-label">Next Renewal</span>
                  <span className="supplier-metric-value">
                    {supplier.renewalDate
                      ? new Date(supplier.renewalDate).toLocaleDateString('en-GB', {
                          day: 'numeric',
                          month: 'short',
                          year: 'numeric',
                        })
                      : 'No contract'}
                  </span>
                </div>
                <div className="supplier-metric">
                  <span className="supplier-metric-label">Risk Score</span>
                  <span
                    className={`supplier-metric-value ${
                      supplier.riskScore > 70 ? 'bad' : supplier.riskScore > 40 ? 'warning' : 'good'
                    }`}
                  >
                    {supplier.riskScore}/100
                  </span>
                </div>
                <div className="supplier-metric">
                  <span className="supplier-metric-label">Last Order</span>
                  <span className="supplier-metric-value">
                    {supplier.lastOrderDate
                      ? new Date(supplier.lastOrderDate).toLocaleDateString('en-GB', {
                          day: 'numeric',
                          month: 'short',
                          year: 'numeric',
                        })
                      : 'No orders'}
                  </span>
                </div>
              </div>

              {/* Progress bar visual for risk */}
              <div className="mt-3 pt-2 border-t border-gray-100">
                <div className="flex items-center justify-between text-[10px] text-gray-500 mb-1">
                  <span>Risk Spectrum</span>
                  <span className="font-semibold text-gray-700">{supplier.riskScore}%</span>
                </div>
                <div className="w-full bg-gray-100 rounded-full h-1.5 overflow-hidden">
                  <div
                    className={`h-1.5 rounded-full ${
                      supplier.riskScore > 70
                        ? 'bg-red-500'
                        : supplier.riskScore > 40
                        ? 'bg-amber-500'
                        : 'bg-emerald-500'
                    }`}
                    style={{ width: `${Math.min(supplier.riskScore, 100)}%` }}
                  ></div>
                </div>
              </div>

              <div className="flex items-center justify-between mt-4">
                <button
                  type="button"
                  onClick={(event) => handleDelete(event, supplier)}
                  className="btn btn-secondary btn-sm flex items-center gap-1 text-red-600 hover:bg-red-50"
                  aria-label={`Delete ${supplier.name}`}
                >
                  <Trash2 size={14} /> Delete
                </button>

                <span className="text-xs font-semibold text-primary-600 flex items-center gap-1">
                  View 360 <ChevronRight size={14} />
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}

      {/* Add Supplier Modal */}
      <AddSupplierModal
        isOpen={isAddModalOpen}
        onClose={handleCloseAddModal}
        onSupplierCreated={() => loadData()}
        categories={categories}
      />
    </div>
  );
}
