import { useState, useEffect, useMemo } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Minus,
  RefreshCw,
  Search,
  ExternalLink,
  ShieldCheck,
  AlertTriangle,
  Info,
  CheckCircle,
  Building2,
  Calendar,
  Globe,
  Sparkles,
  Layers,
  ArrowUpRight,
  ArrowDownRight,
  FileText,
} from 'lucide-react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  Cell,
} from 'recharts';
import { getPricingAnalysis, runPricingResearch, refreshPricingResearch } from '../../services';

const MATCH_BADGES = {
  high: { label: 'High Match', color: 'badge-success', icon: CheckCircle },
  partial: { label: 'Partial Match', color: 'badge-warning', icon: AlertTriangle },
  low: { label: 'Low Match', color: 'badge-secondary', icon: Info },
  not_comparable: { label: 'Not Comparable', color: 'badge-danger', icon: AlertTriangle },
};

export default function MarketPriceBenchmarking({ supplier, onBack }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [researching, setResearching] = useState(false);
  const [error, setError] = useState(null);

  // Filters & Controls
  const [selectedRegion, setSelectedRegion] = useState('India');
  const [selectedPeriod, setSelectedPeriod] = useState('Current Quarter');
  const [sourceFilter, setSourceFilter] = useState('all'); // 'all' | 'high' | 'partial'
  const [selectedSources, setSelectedSources] = useState(null);

  useEffect(() => {
    loadPricingData();
  }, [supplier.id]);

  async function loadPricingData() {
    setLoading(true);
    setError(null);
    try {
      const res = await getPricingAnalysis(supplier.id);
      if (res && res.status === 'success' && res.data) {
        setData(res.data);
      } else {
        setError(res?.message || 'Failed to load market price benchmark analysis');
      }
    } catch (err) {
      console.error('Failed to load pricing data:', err);
      setError(err.message || 'Error connecting to market price research API');
    } finally {
      setLoading(false);
    }
  }

  async function handleRefresh(force = true) {
    setResearching(true);
    setError(null);
    try {
      const res = await refreshPricingResearch(supplier.id, {
        region: selectedRegion,
        comparison_period: selectedPeriod,
        force_refresh: force,
      });
      if (res && res.status === 'success' && res.data) {
        setData(res.data);
      } else {
        setError(res?.message || 'Refresh failed');
      }
    } catch (err) {
      console.error('Refresh failed:', err);
      setError(err.message || 'Error executing web market research');
    } finally {
      setResearching(false);
    }
  }

  // Format currency helpers
  const currencySymbol = useMemo(() => {
    const c = data?.contract_details?.currency || 'INR';
    if (c === 'INR') return '₹';
    if (c === 'USD') return '$';
    if (c === 'EUR') return '€';
    return `${c} `;
  }, [data]);

  const unit = data?.contract_details?.unit_of_measurement || 'kg';

  function formatMoney(amount) {
    if (amount === null || amount === undefined) return '—';
    return `${currencySymbol}${Number(amount).toLocaleString('en-IN', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }

  // Bar Chart Data Preparation
  const chartData = useMemo(() => {
    if (!data) return [];
    const items = [];

    // 1. Contract Bar
    const contractPrice = Number(data.contract_details?.contract_unit_price);
    if (Number.isFinite(contractPrice) && contractPrice > 0) {
      items.push({
        name: 'Contract Price',
        source: `${data.supplier_name} (Contract)`,
        price: contractPrice,
        type: 'contract',
        match: 'Contract Baseline',
        color: '#4F46E5', // Primary indigo
      });
    }

    // 2. Observations
    const obsList = data.observations || [];
    obsList.forEach((obs) => {
      items.push({
        name: obs.source_name,
        source: obs.source_name,
        price: obs.normalized_price,
        rawPrice: obs.raw_price,
        rawCurrency: obs.raw_currency,
        rawUnit: obs.raw_unit,
        type: 'market',
        match: obs.match_classification,
        color:
          obs.match_classification === 'high'
            ? '#10B981' // Green for high match
            : obs.match_classification === 'partial'
            ? '#F59E0B' // Amber for partial match
            : '#9CA3AF', // Gray for low
      });
    });

    return items;
  }, [data]);

  const visibleChartData = useMemo(
    () => selectedSources ? chartData.filter((item) => selectedSources.includes(item.source)) : chartData,
    [chartData, selectedSources]
  );

  const toggleChartSource = (source) => {
    setSelectedSources((current) => {
      const selected = current || chartData.map((item) => item.source);
      const next = selected.includes(source)
        ? selected.filter((item) => item !== source)
        : [...selected, source];
      return next.length === chartData.length ? null : next;
    });
  };

  // Filtered observations for table
  const filteredObservations = useMemo(() => {
    if (!data?.observations) return [];
    if (sourceFilter === 'high') {
      return data.observations.filter((o) => o.match_classification === 'high');
    }
    if (sourceFilter === 'partial') {
      return data.observations.filter(
        (o) => o.match_classification === 'high' || o.match_classification === 'partial'
      );
    }
    return data.observations;
  }, [data, sourceFilter]);

  if (loading) {
    return (
      <div className="card">
        <div className="card-body py-24 text-center">
          <div className="loading-spinner mx-auto mb-4"></div>
          <h3 className="text-lg font-semibold text-gray-800">
            Analyzing Contract & Conducting Live Market Research...
          </h3>
          <p className="text-sm text-gray-500 mt-2 max-w-md mx-auto">
            Extracting material specifications, querying B2B web pricing databases, validating grades,
            and computing statistical benchmarks...
          </p>
        </div>
      </div>
    );
  }

  const contract = data?.contract_details;
  const insight = data?.ai_insight;
  const isAboveMarket = (data?.variance_pct || 0) > 3.0;
  const isBelowMarket = (data?.variance_pct || 0) < -3.0;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header with Back button and Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-gray-200">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-2xl font-bold text-gray-900">
              Market Price Benchmarking
            </h2>
            <span className="badge badge-info text-xs">AI & Web Intelligence</span>
          </div>
          <p className="text-xs text-gray-500 mt-1">
            Real-time B2B market rates, grade-level matching, and contractual price variance analysis for{' '}
            <strong className="text-gray-700">{supplier.name}</strong>.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          {onBack && (
            <button type="button" className="btn btn-secondary btn-sm" onClick={onBack}>
              ← Back to Actions
            </button>
          )}
          <button
            type="button"
            className="btn btn-primary btn-sm flex items-center gap-1.5 shadow-sm"
            onClick={() => handleRefresh(true)}
            disabled={researching}
          >
            <RefreshCw size={14} className={researching ? 'animate-spin' : ''} />
            <span>{researching ? 'Conducting Research...' : 'Refresh Market Prices'}</span>
          </button>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 flex items-center gap-3">
          <AlertTriangle size={20} className="text-red-500 shrink-0" />
          <div className="flex-1">{error}</div>
          <button
            type="button"
            className="btn btn-secondary btn-sm text-xs"
            onClick={() => handleRefresh(true)}
            disabled={researching}
          >
            {researching ? 'Retrying...' : 'Retry'}
          </button>
        </div>
      )}

      {data?.research_notice && (
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-900 flex items-start gap-3">
          <AlertTriangle size={20} className="text-amber-600 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold">Live market comparison is unavailable</p>
            <p className="mt-0.5 text-amber-800">{data.research_notice}</p>
          </div>
        </div>
      )}

      {/* SECTION A: Contract Information Card */}
      {contract && (
        <div className="card bg-gradient-to-r from-blue-50/60 via-indigo-50/40 to-white border border-indigo-100">
          <div className="card-body p-5">
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 text-xs font-semibold text-primary-700 uppercase tracking-wider mb-1">
                  <FileText size={14} /> Active Contract Specification
                </div>
                <h3 className="text-lg font-bold text-gray-900">
                  {contract.material_name}
                  {contract.grade && (
                    <span className="ml-2 text-sm font-medium text-primary-800 bg-primary-100 px-2.5 py-0.5 rounded-full border border-primary-200">
                      {contract.grade}
                    </span>
                  )}
                </h3>
                <div className="text-xs text-gray-500 mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
                  <span>
                    Supplier: <strong className="text-gray-700">{contract.supplier_name || supplier.name}</strong>
                  </span>
                  {contract.product_code && (
                    <span>
                      Product Code: <strong className="font-mono text-gray-700">{contract.product_code}</strong>
                    </span>
                  )}
                  {contract.contract_id && (
                    <span>
                      Contract ID: <span className="badge badge-info text-[10px]">{contract.contract_id}</span>
                    </span>
                  )}
                </div>
              </div>

              {/* Specification pills */}
              <div className="flex flex-wrap gap-2 text-xs">
                {contract.incoterms && (
                  <div className="px-3 py-1.5 bg-white rounded-lg border border-gray-200 shadow-xs">
                    <span className="text-gray-400 block text-[10px] uppercase font-semibold">Delivery Terms</span>
                    <span className="font-semibold text-gray-800">{contract.incoterms}</span>
                  </div>
                )}
                {contract.tax_inclusion && (
                  <div className="px-3 py-1.5 bg-white rounded-lg border border-gray-200 shadow-xs">
                    <span className="text-gray-400 block text-[10px] uppercase font-semibold">Tax Treatment</span>
                    <span className="font-semibold text-gray-800">{contract.tax_inclusion}</span>
                  </div>
                )}
                {contract.annual_estimated_quantity && (
                  <div className="px-3 py-1.5 bg-white rounded-lg border border-gray-200 shadow-xs">
                    <span className="text-gray-400 block text-[10px] uppercase font-semibold">Annual Est. Volume</span>
                    <span className="font-semibold text-gray-800">
                      {Number(contract.annual_estimated_quantity).toLocaleString('en-IN')} {unit}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Technical Characteristics text */}
            {contract.technical_characteristics && (
              <div className="mt-3 pt-3 border-t border-indigo-100/70 text-xs text-gray-600 flex items-start gap-2">
                <Info size={14} className="text-primary-500 shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold text-gray-700">Contract Technical Specifications: </span>
                  <span>{contract.technical_characteristics}</span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* SECTION B: KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* 1. Contract Price */}
        <div className="card">
          <div className="card-body p-5">
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
              Contracted Unit Price
            </div>
            <div className="text-2xl font-bold text-gray-900">
              {formatMoney(contract?.contract_unit_price)}
              <span className="text-sm font-normal text-gray-500 ml-1">/ {unit}</span>
            </div>
            <div className="text-xs text-gray-500 mt-2 flex items-center gap-1">
              <ShieldCheck size={13} className="text-primary-600" />
              <span>Grounded in active supply agreement</span>
            </div>
          </div>
        </div>

        {/* 2. Market Benchmark Median */}
        <div className="card">
          <div className="card-body p-5">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                Market Benchmark (Median)
              </span>
              <span
                className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                  data?.confidence_level === 'High'
                    ? 'bg-emerald-100 text-emerald-800'
                    : 'bg-amber-100 text-amber-800'
                }`}
                title={`Confidence Score: ${data?.confidence_score || 0}%`}
              >
                {data?.confidence_level || 'Moderate'}
              </span>
            </div>
            <div className="text-2xl font-bold text-emerald-700">
              {formatMoney(data?.market_benchmark_median)}
              <span className="text-sm font-normal text-gray-500 ml-1">/ {unit}</span>
            </div>
            <div className="text-xs text-gray-500 mt-2">
              Range: {formatMoney(data?.market_min_price)} – {formatMoney(data?.market_max_price)}
            </div>
          </div>
        </div>

        {/* 3. Price Variance % */}
        <div className="card">
          <div className="card-body p-5">
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
              Price Variance vs Market
            </div>
            <div
              className={`text-2xl font-bold flex items-center gap-1.5 ${
                isAboveMarket
                  ? 'text-red-600'
                  : isBelowMarket
                  ? 'text-emerald-600'
                  : 'text-blue-600'
              }`}
            >
              {isAboveMarket ? (
                <ArrowUpRight size={26} />
              ) : isBelowMarket ? (
                <ArrowDownRight size={26} />
              ) : (
                <Minus size={24} />
              )}
              <span>{data?.variance_pct !== null ? `${data?.variance_pct > 0 ? '+' : ''}${data?.variance_pct}%` : '—'}</span>
            </div>
            <div className="text-xs text-gray-500 mt-2">
              {isAboveMarket ? (
                <span className="text-red-700 font-medium">Paying above median market rate</span>
              ) : isBelowMarket ? (
                <span className="text-emerald-700 font-medium">Advantageous rate vs market</span>
              ) : (
                <span>In line with market average (+/-3%)</span>
              )}
            </div>
          </div>
        </div>

        {/* 4. Potential Annual Difference */}
        <div className="card">
          <div className="card-body p-5">
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
              Potential Annual Difference
            </div>
            <div
              className={`text-2xl font-bold ${
                isAboveMarket
                  ? 'text-red-600'
                  : isBelowMarket
                  ? 'text-emerald-600'
                  : 'text-gray-800'
              }`}
            >
              {data?.potential_annual_difference !== null
                ? `${data?.potential_annual_difference > 0 ? '+' : ''}${formatMoney(data?.potential_annual_difference)}`
                : '—'}
            </div>
            <div className="text-[11px] text-gray-400 mt-2">
              Based on {Number(contract?.annual_estimated_quantity || 0).toLocaleString('en-IN')} {unit} volume (est.)
            </div>
          </div>
        </div>
      </div>

      {/* SECTION G: Research Controls */}
      <div className="card p-4 bg-gray-50 border border-gray-200">
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 text-xs">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5">
              <Globe size={14} className="text-gray-500" />
              <span className="font-semibold text-gray-700">Market Region:</span>
              <select
                className="select select-sm text-xs py-1"
                value={selectedRegion}
                onChange={(e) => {
                  setSelectedRegion(e.target.value);
                  handleRefresh(true);
                }}
              >
                <option value="India">India (Domestic B2B)</option>
                <option value="Global">Global / International</option>
                <option value="Europe">Europe (EUR)</option>
                <option value="North America">North America (USD)</option>
                <option value="Asia-Pacific">Asia-Pacific (APAC)</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5">
              <Calendar size={14} className="text-gray-500" />
              <span className="font-semibold text-gray-700">Comparison Period:</span>
              <select
                className="select select-sm text-xs py-1"
                value={selectedPeriod}
                onChange={(e) => {
                  setSelectedPeriod(e.target.value);
                  handleRefresh(true);
                }}
              >
                <option value="Current Quarter">Current Quarter</option>
                <option value="Last 30 Days">Last 30 Days</option>
                <option value="Last 6 Months">Last 6 Months</option>
                <option value="Last 1 Year">Last 1 Year</option>
              </select>
            </div>
          </div>

          <div className="flex items-center gap-2 text-gray-500 text-[11px]">
            <span>Last Research Run:</span>
            <span className="font-mono font-semibold text-gray-700">
              {data?.created_at ? new Date(data.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'Just now'}
            </span>
          </div>
        </div>
      </div>

      {/* SECTION C & D: Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Main Chart: Contract vs Market Prices (Bar Chart) */}
        <div className="card">
          <div className="card-header flex items-center justify-between">
            <div>
              <h3 className="card-title text-base font-bold text-gray-900">
                Contract vs Market Benchmark Prices
              </h3>
              <p className="text-xs text-gray-500 mt-0.5">
                Normalized to {contract?.currency}/{unit} on {contract?.incoterms || 'DDP'} terms
              </p>
            </div>
            <div className="text-xs font-semibold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-200">
              Median: {formatMoney(data?.market_benchmark_median)}/{unit}
            </div>
          </div>

          <div className="card-body">
            <div className="pricing-chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={visibleChartData} margin={{ top: 20, right: 30, left: 10, bottom: 40 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E5E7EB" />
                  <XAxis
                    dataKey="name"
                    angle={-25}
                    textAnchor="end"
                    interval={0}
                    height={55}
                    tick={{ fontSize: 11, fill: '#6B7280' }}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: '#6B7280' }}
                    domain={[0, (max) => Math.ceil(max * 1.15)]}
                    tickFormatter={(val) => `${currencySymbol}${val}`}
                  />
                  <Tooltip
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const item = payload[0].payload;
                      return (
                        <div className="bg-white p-3 rounded-lg shadow-lg border border-gray-200 text-xs">
                          <p className="font-bold text-gray-800">{item.source}</p>
                          <p className="text-sm font-semibold text-primary-700 mt-1">
                            Normalized: {formatMoney(item.price)} / {unit}
                          </p>
                          {item.rawPrice && item.rawPrice !== item.price && (
                            <p className="text-gray-500 text-[11px]">
                              Raw quote: {item.rawCurrency} {item.rawPrice} / {item.rawUnit}
                            </p>
                          )}
                          <div className="mt-1.5 pt-1 border-t border-gray-100 flex items-center justify-between gap-2">
                            <span className="text-gray-500 capitalize">{item.type}</span>
                            <span className="capitalize font-semibold text-gray-700">{item.match}</span>
                          </div>
                        </div>
                      );
                    }}
                  />
                  {data?.market_benchmark_median && (
                    <ReferenceLine
                      y={data.market_benchmark_median}
                      stroke="#10B981"
                      strokeDasharray="4 4"
                      label={{
                        value: `Market Median: ${formatMoney(data.market_benchmark_median)}`,
                        position: 'top',
                        fill: '#10B981',
                        fontSize: 11,
                        fontWeight: 'bold',
                      }}
                    />
                  )}
                  <Bar dataKey="price" radius={[4, 4, 0, 0]} maxBarSize={45}>
                    {visibleChartData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} cursor="pointer" onClick={() => toggleChartSource(entry.source)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-2 mt-3 text-xs border-t border-gray-100 pt-3">
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => setSelectedSources(null)}>Show all</button>
              {chartData.map((item) => (
                <button key={item.source} type="button" onClick={() => toggleChartSource(item.source)} className={`btn btn-secondary btn-sm flex items-center gap-1.5 transition-opacity ${selectedSources && !selectedSources.includes(item.source) ? 'opacity-40' : ''}`}>
                  <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: item.color }} />
                  <span>{item.name}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* SECTION D: Market Price Trend (Line Chart) */}
        <div className="card">
          <div className="card-header flex items-center justify-between">
            <div>
              <h3 className="card-title text-base font-bold text-gray-900">
                Market Price Trajectory & Trend
              </h3>
              <p className="text-xs text-gray-500 mt-0.5">
                Published index & spot trends over last 6 months
              </p>
            </div>
            <span className="badge badge-info text-xs">6-Month Trend</span>
          </div>

          <div className="card-body">
            {data?.historical_trend?.length > 0 ? (
              <div className="pricing-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data.historical_trend} margin={{ top: 20, right: 30, left: 10, bottom: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E5E7EB" />
                    <XAxis dataKey="period" tick={{ fontSize: 11, fill: '#6B7280' }} />
                    <YAxis
                      tick={{ fontSize: 11, fill: '#6B7280' }}
                      domain={[0, (max) => Math.ceil(max * 1.15)]}
                      tickFormatter={(val) => `${currencySymbol}${val}`}
                    />
                    <Tooltip
                      formatter={(val, name) => [
                        `${currencySymbol}${val} / ${unit}`,
                        name === 'marketPrice' ? 'Market Index' : 'Contract Price',
                      ]}
                    />
                    <Legend />
                    {contract?.contract_unit_price && (
                      <ReferenceLine
                        y={contract.contract_unit_price}
                        stroke="#4F46E5"
                        strokeDasharray="3 3"
                        label={{
                          value: `Contract: ${formatMoney(contract.contract_unit_price)}`,
                          position: 'insideBottomRight',
                          fill: '#4F46E5',
                          fontSize: 10,
                        }}
                      />
                    )}
                    <Line
                      type="monotone"
                      dataKey="marketPrice"
                      name="Market Spot Rate"
                      stroke="#10B981"
                      strokeWidth={2.5}
                      dot={{ r: 4, fill: '#10B981' }}
                      activeDot={{ r: 6 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="h-72 flex flex-col items-center justify-center text-center p-6 text-gray-400">
                <Calendar size={36} className="mb-2 text-gray-300" />
                <p className="font-semibold text-gray-700 text-sm">No Historical Trend Observations Recorded</p>
                <p className="text-xs text-gray-500 mt-1 max-w-sm">
                  Historical tracking begins with today's initial market benchmark. Trend data will accumulate over subsequent research runs.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* SECTION F: AI Procurement Insight */}
      {insight && (
        <div className="card bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/40 border border-indigo-200">
          <div className="card-header border-b border-indigo-100 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-primary-600 text-white flex items-center justify-center font-bold shadow-xs">
                <Sparkles size={18} />
              </div>
              <div>
                <h3 className="font-bold text-gray-900 text-base leading-tight">
                  AI Procurement Insight & Negotiation Intelligence
                </h3>
                <p className="text-xs text-gray-500">
                  Automated strategic synthesis of market observations vs contractual obligations
                </p>
              </div>
            </div>

            <span
              className={`text-xs font-bold px-3 py-1 rounded-full border ${
                insight.verdict === 'Above Market'
                  ? 'bg-red-50 text-red-700 border-red-200'
                  : insight.verdict === 'Below Market'
                  ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                  : 'bg-blue-50 text-blue-700 border-blue-200'
              }`}
            >
              {insight.verdict}
            </span>
          </div>

          <div className="card-body space-y-4">
            {/* Summary & Financial Impact */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="p-4 bg-white rounded-lg border border-gray-200 shadow-xs">
                <h4 className="text-xs font-bold text-gray-700 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
                  <Info size={14} className="text-primary-600" /> Benchmark Evaluation
                </h4>
                <p className="text-xs text-gray-700 leading-relaxed">{insight.summary}</p>
              </div>

              <div className="p-4 bg-white rounded-lg border border-gray-200 shadow-xs">
                <h4 className="text-xs font-bold text-gray-700 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
                  <TrendingUp size={14} className="text-amber-600" /> Financial Impact & Exposure
                </h4>
                <p className="text-xs text-gray-700 leading-relaxed">{insight.financial_impact}</p>
                <div className="mt-2 text-[11px] text-gray-500">
                  Reliability: <strong>{insight.reliability_evaluation}</strong>
                </div>
              </div>
            </div>

            {/* Strategic Recommendations and Caveats */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Recommendations */}
              {insight.recommended_actions?.length > 0 && (
                <div className="p-4 bg-white rounded-lg border border-gray-200 shadow-xs">
                  <h4 className="text-xs font-bold text-emerald-800 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    <CheckCircle size={14} className="text-emerald-600" /> Recommended Procurement Actions
                  </h4>
                  <ul className="space-y-1.5 text-xs text-gray-700">
                    {insight.recommended_actions.map((act, i) => (
                      <li key={i} className="flex items-start gap-2">
                        <span className="font-bold text-primary-600 shrink-0">{i + 1}.</span>
                        <span>{act}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Caveats / Terms Checks */}
              {insight.spec_and_terms_caveats?.length > 0 && (
                <div className="p-4 bg-white rounded-lg border border-gray-200 shadow-xs">
                  <h4 className="text-xs font-bold text-gray-700 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    <AlertTriangle size={14} className="text-amber-500" /> Terms Normalization & Caveats
                  </h4>
                  <ul className="space-y-1.5 text-xs text-gray-600">
                    {insight.spec_and_terms_caveats.map((cav, i) => (
                      <li key={i} className="flex items-start gap-2">
                        <span className="text-amber-500 shrink-0">•</span>
                        <span>{cav}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* SECTION E: Market Research Source Table */}
      <div className="card">
        <div className="card-header flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h3 className="card-title text-base font-bold text-gray-900">
              Discovered Market Research Sources ({filteredObservations.length})
            </h3>
            <p className="text-xs text-gray-500 mt-0.5">
              Verified independent B2B web discovery with grade-level matching and clickable sources
            </p>
          </div>

          <div className="flex items-center gap-1 bg-gray-100 p-1 rounded-lg self-start sm:self-auto text-xs">
            <button
              type="button"
              className={`px-3 py-1 rounded-md transition-all ${
                sourceFilter === 'all' ? 'bg-white shadow-xs font-semibold text-gray-900' : 'text-gray-600'
              }`}
              onClick={() => setSourceFilter('all')}
            >
              All ({data?.observations?.length || 0})
            </button>
            <button
              type="button"
              className={`px-3 py-1 rounded-md transition-all ${
                sourceFilter === 'high' ? 'bg-white shadow-xs font-semibold text-emerald-800' : 'text-gray-600'
              }`}
              onClick={() => setSourceFilter('high')}
            >
              High Match ({data?.observations?.filter((o) => o.match_classification === 'high').length || 0})
            </button>
            <button
              type="button"
              className={`px-3 py-1 rounded-md transition-all ${
                sourceFilter === 'partial' ? 'bg-white shadow-xs font-semibold text-amber-800' : 'text-gray-600'
              }`}
              onClick={() => setSourceFilter('partial')}
            >
              Comparable ({data?.observations?.filter((o) => o.match_classification !== 'not_comparable').length || 0})
            </button>
          </div>
        </div>

        <div className="card-body p-0">
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>Source Name</th>
                  <th>Material & Grade</th>
                  <th>Normalized Price</th>
                  <th>Raw Quote</th>
                  <th>Location</th>
                  <th>Date</th>
                  <th>Match Status</th>
                  <th>Price Type</th>
                  <th>Source Link</th>
                </tr>
              </thead>
              <tbody>
                {filteredObservations.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="text-center py-8 text-gray-400">
                      No market research observations match the selected filter.
                    </td>
                  </tr>
                ) : (
                  filteredObservations.map((obs) => {
                    const badge = MATCH_BADGES[obs.match_classification] || MATCH_BADGES.high;
                    const BadgeIcon = badge.icon;
                    return (
                      <tr key={obs.id}>
                        <td className="font-medium text-gray-900">
                          <div className="font-semibold">{obs.source_name}</div>
                          {obs.delivery_conditions && obs.delivery_conditions !== 'Unspecified' && (
                            <span className="text-[10px] text-gray-400 uppercase font-mono">
                              Incoterm: {obs.delivery_conditions}
                            </span>
                          )}
                        </td>

                        <td>
                          <div className="font-medium text-gray-800 text-xs">{obs.material_name}</div>
                          {obs.grade && (
                            <span className="text-[11px] text-primary-700 bg-primary-50 px-1.5 py-0.5 rounded font-mono">
                              {obs.grade}
                            </span>
                          )}
                        </td>

                        <td>
                          <div className="font-bold text-gray-900 text-sm">
                            {formatMoney(obs.normalized_price)}
                            <span className="text-xs font-normal text-gray-500"> / {unit}</span>
                          </div>
                        </td>

                        <td className="text-xs text-gray-500 font-mono">
                          {obs.raw_price ? `${obs.raw_currency} ${obs.raw_price} / ${obs.raw_unit}` : '—'}
                        </td>

                        <td className="text-xs text-gray-600 whitespace-nowrap">{obs.location || 'India'}</td>

                        <td className="text-xs text-gray-500 whitespace-nowrap">{obs.observation_date || 'Recent'}</td>

                        <td>
                          <span
                            className={`badge ${badge.color} inline-flex items-center gap-1 text-[11px]`}
                            title={obs.match_rationale || ''}
                          >
                            <BadgeIcon size={11} /> {badge.label}
                          </span>
                        </td>

                        <td>
                          <span className="badge badge-info text-[10px] capitalize">
                            {obs.price_type || 'Quote'}
                          </span>
                        </td>

                        <td>
                          {obs.source_url ? (
                            <a
                              href={obs.source_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="btn btn-secondary btn-sm py-1 px-2.5 text-xs inline-flex items-center gap-1 text-primary-600 hover:text-primary-800"
                              title={`Open source: ${obs.source_url}`}
                            >
                              <span>Visit</span>
                              <ExternalLink size={12} />
                            </a>
                          ) : (
                            <span className="text-xs text-gray-400">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
