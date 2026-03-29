import { useApi } from '../hooks/useApi';
import { api } from '../api/client';
import Icon from '../components/Icon';
import StatusChip from '../components/StatusChip';

function formatTimeAgo(dateStr) {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function SparkBars({ values = [40, 65, 55, 80, 70, 90, 75] }) {
  const max = Math.max(...values, 1);
  return (
    <div className="flex items-end gap-[3px] h-8">
      {values.map((v, i) => (
        <div
          key={i}
          className="w-[5px] rounded-full bg-primary/30"
          style={{ height: `${(v / max) * 100}%` }}
        />
      ))}
    </div>
  );
}

function MetricCard({ icon, label, value, unit, change, positive, sparkValues }) {
  return (
    <div className="bg-surface-container-lowest rounded-xl shadow-sm p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="w-9 h-9 rounded-lg bg-primary/8 flex items-center justify-center">
          <Icon name={icon} className="text-primary text-[20px]" />
        </div>
        {change !== undefined && (
          <span
            className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${
              positive
                ? 'bg-secondary/10 text-secondary'
                : 'bg-error/10 text-error'
            }`}
          >
            {positive ? '+' : ''}{change}
          </span>
        )}
      </div>
      <div>
        <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1">
          {label}
        </p>
        <p className="text-2xl font-bold text-on-surface">
          {value}
          {unit && <span className="text-sm font-medium text-on-surface-variant ml-0.5">{unit}</span>}
        </p>
      </div>
      <SparkBars values={sparkValues} />
    </div>
  );
}

function TopologyHub() {
  const rings = [140, 100, 60];
  const satellites = [
    { angle: 30, dist: 130, color: 'bg-secondary' },
    { angle: 80, dist: 120, color: 'bg-secondary' },
    { angle: 150, dist: 135, color: 'bg-tertiary' },
    { angle: 200, dist: 110, color: 'bg-error' },
    { angle: 260, dist: 128, color: 'bg-secondary' },
    { angle: 320, dist: 115, color: 'bg-tertiary' },
  ];

  return (
    <div className="bg-surface-container-lowest rounded-xl shadow-sm p-6 flex flex-col h-full">
      <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1">
        Network Topology
      </p>
      <h3 className="text-lg font-bold text-on-surface mb-4">Network Hubs</h3>

      <div className="flex-1 flex items-center justify-center relative min-h-[220px]">
        <svg viewBox="0 0 300 300" className="w-full h-full max-w-[280px]">
          {rings.map((r, i) => (
            <circle
              key={i}
              cx="150"
              cy="150"
              r={r}
              fill="none"
              stroke="#c1c6d7"
              strokeWidth="1"
              strokeDasharray="6 4"
              opacity={0.6}
            />
          ))}
          {satellites.map((s, i) => {
            const rad = (s.angle * Math.PI) / 180;
            const x = 150 + Math.cos(rad) * s.dist;
            const y = 150 + Math.sin(rad) * s.dist;
            const fill =
              s.color === 'bg-secondary'
                ? '#006c4f'
                : s.color === 'bg-error'
                ? '#ba1a1a'
                : '#585c61';
            return (
              <g key={i}>
                <line
                  x1="150"
                  y1="150"
                  x2={x}
                  y2={y}
                  stroke="#c1c6d7"
                  strokeWidth="1"
                  strokeDasharray="3 3"
                />
                <circle cx={x} cy={y} r="6" fill={fill} />
              </g>
            );
          })}
          <circle cx="150" cy="150" r="18" fill="#0059bb" />
          <text
            x="150"
            y="155"
            textAnchor="middle"
            fill="#ffffff"
            fontSize="14"
            fontFamily="Material Symbols Outlined"
          >
            R
          </text>
        </svg>
      </div>

      <a
        href="/topology"
        className="inline-flex items-center gap-1 text-primary text-sm font-semibold mt-2 hover:underline"
      >
        Explore Detailed Topology
        <Icon name="arrow_forward" className="text-[16px]" />
      </a>
    </div>
  );
}

function AlertRow({ finding }) {
  const severityMap = {
    critical: { icon: 'warning', iconClass: 'text-error', variant: 'error' },
    high: { icon: 'warning', iconClass: 'text-error', variant: 'error' },
    medium: { icon: 'error', iconClass: 'text-tertiary', variant: 'warning' },
    low: { icon: 'info', iconClass: 'text-primary', variant: 'info' },
    info: { icon: 'check_circle', iconClass: 'text-secondary', variant: 'success' },
  };

  const sev = severityMap[finding.severity] || severityMap.medium;

  return (
    <div className="flex items-center gap-4 py-3 px-4 hover:bg-surface-container-low/50 rounded-lg transition-colors">
      <div
        className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${
          sev.variant === 'error'
            ? 'bg-error/10'
            : sev.variant === 'warning'
            ? 'bg-orange-400/10'
            : sev.variant === 'success'
            ? 'bg-secondary/10'
            : 'bg-primary/10'
        }`}
      >
        <Icon name={sev.icon} className={`text-[20px] ${sev.iconClass}`} fill />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <p className="text-sm font-semibold text-on-surface truncate">{finding.title}</p>
          <StatusChip variant={sev.variant}>{finding.category || finding.severity}</StatusChip>
        </div>
        <p className="text-xs text-on-surface-variant truncate">
          {finding.description || `Affected: ${finding.affected_entity || 'Unknown'}`}
        </p>
      </div>

      <span className="text-xs text-on-surface-variant whitespace-nowrap shrink-0">
        {formatTimeAgo(finding.created_at)}
      </span>

      <button className="w-8 h-8 rounded-lg hover:bg-surface-container flex items-center justify-center shrink-0 text-on-surface-variant hover:text-on-surface transition-colors">
        <Icon name="chevron_right" className="text-[20px]" />
      </button>
    </div>
  );
}

export default function Dashboard() {
  const {
    data: findings,
    loading: findingsLoading,
    error: findingsError,
  } = useApi(() => api.findings({ limit: 6 }));

  const {
    data: healthDeps,
    loading: healthLoading,
    error: healthError,
  } = useApi(() => api.healthDeps());

  const loading = findingsLoading || healthLoading;
  const error = findingsError || healthError;

  // Derive health stats from dependencies response
  const deps = healthDeps?.dependencies || healthDeps || {};
  const totalDeps = Object.keys(deps).length || 4;
  const healthyCount = Object.values(deps).filter(
    (d) => d === 'ok' || d === 'healthy' || d?.status === 'ok' || d?.status === 'healthy'
  ).length;
  const healthPct = totalDeps > 0 ? Math.round((healthyCount / totalDeps) * 100) : 0;

  // Mock counts derived from findings for the hero card
  const findingsList = Array.isArray(findings) ? findings : findings?.items || [];
  const criticalCount = findingsList.filter(
    (f) => f.severity === 'critical' || f.severity === 'high'
  ).length;
  const warningCount = findingsList.filter((f) => f.severity === 'medium').length;
  const activeCount = findingsList.length - criticalCount - warningCount;

  if (error) {
    return (
      <div className="p-8">
        <div className="bg-error/10 text-error rounded-xl p-6 flex items-center gap-3">
          <Icon name="error" className="text-2xl" fill />
          <div>
            <p className="font-semibold">Failed to load dashboard data</p>
            <p className="text-sm opacity-80">{error.message || String(error)}</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-[1440px] mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="w-2 h-2 rounded-full bg-secondary" />
            <span className="text-xs font-medium text-on-surface-variant">
              Network Core / Global View
            </span>
          </div>
          <h1 className="text-4xl font-bold text-on-surface">System Overview</h1>
        </div>
        <div className="flex items-center gap-3">
          <button className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold text-on-surface-variant bg-surface-container hover:bg-surface-container-high transition-colors">
            <Icon name="schedule" className="text-[18px]" />
            Last 24 Hours
          </button>
          <button className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold text-on-primary bg-primary hover:bg-primary-container transition-colors">
            <Icon name="download" className="text-[18px]" />
            Export Report
          </button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-on-surface-variant text-sm mb-6">
          <Icon name="hourglass_empty" className="text-[18px] animate-spin" />
          Loading...
        </div>
      )}

      {/* Bento Grid */}
      <div className="grid grid-cols-12 gap-6">
        {/* Global Health Hero + Metric Cards */}
        <div className="col-span-8 flex flex-col gap-6">
          {/* Hero Card */}
          <div className="bg-surface-container-lowest rounded-xl shadow-sm p-8 relative overflow-hidden">
            {/* Background decoration */}
            <div className="absolute -right-20 -top-20 w-80 h-80 rounded-full bg-primary/5 pointer-events-none" />
            <div className="absolute -right-10 -top-10 w-56 h-56 rounded-full bg-primary/3 pointer-events-none" />

            <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1 relative z-10">
              System Health
            </p>
            <h2 className="text-lg font-bold text-on-surface mb-6 relative z-10">
              Global Connectivity
            </h2>

            <div className="flex items-end gap-12 relative z-10">
              <div>
                <span className="text-7xl font-bold text-on-surface leading-none">
                  {loading ? '--' : `${healthPct}%`}
                </span>
              </div>

              <div className="flex items-center gap-8 pb-2">
                <div className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded-full bg-secondary" />
                  <div>
                    <p className="text-xs text-on-surface-variant">Active</p>
                    <p className="text-lg font-bold text-on-surface">
                      {loading ? '-' : Math.max(activeCount, 0)}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded-full bg-tertiary" />
                  <div>
                    <p className="text-xs text-on-surface-variant">Warning</p>
                    <p className="text-lg font-bold text-on-surface">
                      {loading ? '-' : warningCount}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded-full bg-error" />
                  <div>
                    <p className="text-xs text-on-surface-variant">Critical</p>
                    <p className="text-lg font-bold text-on-surface">
                      {loading ? '-' : criticalCount}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* 3 Metric Cards */}
          <div className="grid grid-cols-3 gap-6">
            <MetricCard
              icon="speed"
              label="Avg Latency"
              value="2.4"
              unit="ms"
              change="-12%"
              positive
              sparkValues={[30, 45, 38, 52, 44, 36, 24]}
            />
            <MetricCard
              icon="swap_vert"
              label="Packet Loss"
              value="0.02"
              unit="%"
              change="+0.01%"
              positive={false}
              sparkValues={[5, 8, 6, 12, 9, 7, 4]}
            />
            <MetricCard
              icon="check_circle"
              label="Availability"
              value="99.97"
              unit="%"
              change="+0.1%"
              positive
              sparkValues={[95, 97, 96, 98, 99, 99, 100]}
            />
          </div>
        </div>

        {/* Topology Hub */}
        <div className="col-span-4">
          <TopologyHub />
        </div>

        {/* Recent Alerts */}
        <div className="col-span-12 bg-surface-container-lowest rounded-xl shadow-sm p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1">
                Incident Feed
              </p>
              <h3 className="text-lg font-bold text-on-surface">Recent Alerts</h3>
            </div>
            {findingsList.length > 0 && (
              <StatusChip variant="neutral">{findingsList.length} recent</StatusChip>
            )}
          </div>

          {findingsList.length > 0 ? (
            <div className="divide-y divide-outline-variant/30">
              {findingsList.map((finding) => (
                <AlertRow key={finding.id} finding={finding} />
              ))}
            </div>
          ) : (
            !loading && (
              <div className="flex flex-col items-center justify-center py-12 text-on-surface-variant">
                <Icon name="verified" className="text-5xl mb-2 text-secondary/40" />
                <p className="text-sm font-medium">No recent alerts</p>
                <p className="text-xs">All systems are operating normally</p>
              </div>
            )
          )}

          <a
            href="/findings"
            className="inline-flex items-center gap-1 text-primary text-sm font-semibold mt-4 hover:underline"
          >
            View Incident History
            <Icon name="arrow_forward" className="text-[16px]" />
          </a>
        </div>
      </div>
    </div>
  );
}
