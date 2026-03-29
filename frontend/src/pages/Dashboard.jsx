import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import { api } from '../api/client';
import { useSnapshotStatus } from '../hooks/useSnapshotStatus';
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

function MetricCard({ icon, label, value, sub, change, positive }) {
  return (
    <div className="bg-surface-container-lowest rounded-xl shadow-sm p-5 flex flex-col gap-2">
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
            {change}
          </span>
        )}
      </div>
      <div>
        <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1">
          {label}
        </p>
        <p className="text-2xl font-bold text-on-surface">
          {value}
        </p>
        {sub && <p className="text-xs text-on-surface-variant mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

function LastSnapshotCard({ status, onTrigger }) {
  const running = status?.running;
  const hasRun = status?.finished_at;
  const isOk = status?.result === 'ok';
  const isPartial = status?.result === 'partial';
  const isError = status?.result === 'error';
  const finishedTime = hasRun ? new Date(status.finished_at) : null;

  const formatDur = (s) => {
    if (!s) return '--';
    if (s < 60) return `${s.toFixed(1)}s`;
    return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  };

  return (
    <div className="bg-surface-container-lowest rounded-xl shadow-sm p-6 flex flex-col h-full">
      <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1">
        Snapshots
      </p>
      <h3 className="text-lg font-bold text-on-surface mb-4">Last Run</h3>

      {hasRun ? (
        <div className="flex-1 flex flex-col gap-3">
          {/* Status banner */}
          <div className={`flex items-center gap-3 rounded-xl px-4 py-3 ${
            isError ? 'bg-error/5 border border-error/20'
              : isPartial ? 'bg-tertiary/5 border border-tertiary/20'
              : 'bg-secondary/5 border border-secondary/20'
          }`}>
            <Icon
              name={isError ? 'error_outline' : isPartial ? 'warning' : 'check_circle'}
              className={`text-xl ${isError ? 'text-error' : isPartial ? 'text-tertiary' : 'text-secondary'}`}
              fill
            />
            <div>
              <p className={`text-sm font-bold ${isError ? 'text-error' : isPartial ? 'text-tertiary' : 'text-secondary'}`}>
                {isError ? 'Failed' : isPartial ? 'Partial' : 'Successful'}
              </p>
              <p className="text-[10px] text-on-surface-variant">
                {status.devices_ok || 0} of {status.devices_total || 0} devices snapshotted
              </p>
            </div>
          </div>

          {/* Summary row */}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 bg-surface-container-low rounded-lg px-3 py-2">
              <Icon name="timer" className="text-sm text-primary" />
              <span className="text-xs font-bold text-on-surface">{formatDur(status.duration)}</span>
            </div>
            <div className="flex items-center gap-2 bg-surface-container-low rounded-lg px-3 py-2">
              <Icon name="schedule" className="text-sm text-primary" />
              <div className="flex items-baseline gap-1">
                <span className="text-xs font-bold text-on-surface">{formatTimeAgo(status.finished_at)}</span>
                <span className="text-[10px] text-on-surface-variant">
                  {finishedTime?.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
            </div>
          </div>

          {/* Per-device features */}
          {(status.per_device || []).length > 0 && (
            <div className="space-y-1">
              <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
                Features per device
              </span>
              <div className="space-y-1 max-h-[180px] overflow-y-auto">
                {status.per_device.map((d) => (
                  <div key={d.hostname} className="flex items-center justify-between bg-surface-container-low rounded-lg px-3 py-1.5">
                    <span className="text-[11px] font-bold text-on-surface">{d.hostname}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] text-on-surface-variant">{d.features} features</span>
                      <span className={`w-1.5 h-1.5 rounded-full ${d.ok ? 'bg-secondary' : 'bg-error'}`} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-on-surface-variant gap-2">
          <Icon name="camera" className="text-4xl opacity-30" />
          <p className="text-sm font-semibold">No snapshots yet</p>
          <p className="text-xs opacity-60">Take your first snapshot</p>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between mt-4 pt-4 border-t border-outline/10">
        <a
          href="/snapshots"
          className="inline-flex items-center gap-1 text-primary text-xs font-semibold hover:underline"
        >
          View All
          <Icon name="arrow_forward" className="text-[14px]" />
        </a>
        <button
          onClick={onTrigger}
          disabled={running}
          className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-colors ${
            running
              ? 'bg-tertiary/10 text-tertiary cursor-not-allowed'
              : 'bg-primary text-on-primary hover:bg-primary/90'
          }`}
        >
          {running ? (
            <>
              <div className="w-3.5 h-3.5 border-2 border-tertiary/30 border-t-tertiary rounded-full animate-spin" />
              Snapshot Underway
            </>
          ) : (
            <>
              <Icon name="camera" className="text-[16px]" />
              Take Snapshot
            </>
          )}
        </button>
      </div>
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
          sev.variant === 'error' ? 'bg-error/10'
            : sev.variant === 'warning' ? 'bg-orange-400/10'
            : sev.variant === 'success' ? 'bg-secondary/10'
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
    </div>
  );
}

export default function Dashboard() {
  const { data: metrics, loading: metricsLoading } = useApi(api.dashboardMetrics);
  const { data: findings, loading: findingsLoading } = useApi(() => api.findings({ limit: 8 }));
  const { data: healthDeps, loading: healthLoading } = useApi(api.healthDeps);
  const { data: approvals, loading: approvalsLoading } = useApi(api.approvals);
  const { status: snapStatus, triggerSnapshot } = useSnapshotStatus();

  const loading = metricsLoading || findingsLoading || healthLoading;

  const [findingSevFilter, setFindingSevFilter] = useState(null);
  const findingsList = Array.isArray(findings) ? findings : findings?.items || [];
  const filteredFindings = findingSevFilter
    ? findingsList.filter((f) => {
        const s = f.severity?.toLowerCase();
        if (findingSevFilter === 'high') return s === 'critical' || s === 'high';
        return s === findingSevFilter;
      })
    : findingsList;
  const approvalList = Array.isArray(approvals) ? approvals : [];

  // Device health metrics from dedicated endpoint (aggregated from Grafana inventory + snapshots)
  const m = metrics || {};
  const totalDevices = m.devices?.total || 0;
  const snappedDevices = m.devices?.with_snapshots || 0;
  const intfUp = m.interfaces?.up || 0;
  const intfDown = m.interfaces?.down || 0;
  const intfTotal = m.interfaces?.total || 0;
  const bgpUp = m.bgp?.established || 0;
  const bgpDown = m.bgp?.down || 0;
  const bgpTotal = m.bgp?.total || 0;

  // Global connectivity = weighted average of BGP + interface health
  const hasBgp = bgpTotal > 0;
  const hasIntf = intfTotal > 0;
  const bgpPct = hasBgp ? (bgpUp / bgpTotal) * 100 : null;
  const intfPct = hasIntf ? (intfUp / intfTotal) * 100 : null;
  const connectivityPct =
    bgpPct !== null && intfPct !== null ? Math.round(bgpPct * 0.6 + intfPct * 0.4)
    : bgpPct !== null ? Math.round(bgpPct)
    : intfPct !== null ? Math.round(intfPct)
    : null;

  // Finding counts
  const findingCounts = m.findings || {};
  const criticalCount = (findingCounts.critical || 0) + (findingCounts.high || 0);
  const warningCount = findingCounts.medium || 0;

  // Service health
  const deps = healthDeps?.dependencies || {};
  const servicesUp = Object.values(deps).filter(
    (d) => d?.status === 'ok' || d?.status === 'healthy'
  ).length;
  const servicesTotal = Object.keys(deps).length || 1;

  return (
    <div className="max-w-[1440px] mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className={`w-2 h-2 rounded-full ${connectivityPct === null ? 'bg-outline' : connectivityPct >= 95 ? 'bg-secondary' : connectivityPct >= 80 ? 'bg-tertiary' : 'bg-error'}`} />
            <span className="text-xs font-medium text-on-surface-variant">
              Network Core / Global View
            </span>
          </div>
          <h1 className="text-4xl font-bold text-on-surface">System Overview</h1>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => triggerSnapshot()}
            disabled={snapStatus?.running}
            className={`inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-colors ${
              snapStatus?.running
                ? 'bg-tertiary/10 text-tertiary cursor-not-allowed'
                : 'text-on-primary bg-primary hover:bg-primary/90'
            }`}
          >
            {snapStatus?.running ? (
              <>
                <div className="w-4 h-4 border-2 border-tertiary/30 border-t-tertiary rounded-full animate-spin" />
                Snapshot Underway
              </>
            ) : (
              <>
                <Icon name="camera" className="text-[18px]" />
                Take Snapshot
              </>
            )}
          </button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-on-surface-variant text-sm mb-6">
          <div className="w-4 h-4 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
          Loading network data...
        </div>
      )}

      {/* Bento Grid */}
      <div className="grid grid-cols-12 gap-6">
        {/* Global Connectivity Hero + Metrics */}
        <div className="col-span-8 flex flex-col gap-6">
          {/* Hero Card */}
          <div className="bg-surface-container-lowest rounded-xl shadow-sm p-8 relative overflow-hidden">
            <div className="absolute -right-20 -top-20 w-80 h-80 rounded-full bg-primary/5 pointer-events-none" />

            <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1 relative z-10">
              Network Health
            </p>
            <h2 className="text-lg font-bold text-on-surface mb-6 relative z-10">
              Snapshot Anomalies
            </h2>

            <div className="flex items-end gap-12 relative z-10">
              <div>
                {connectivityPct !== null ? (
                  <span className={`text-7xl font-bold leading-none ${
                    connectivityPct >= 95 ? 'text-secondary' : connectivityPct >= 80 ? 'text-tertiary' : 'text-error'
                  }`}>
                    {loading ? '--' : `${connectivityPct}%`}
                  </span>
                ) : (
                  <span className="text-7xl font-bold leading-none text-on-surface-variant/30">
                    {loading ? '--' : 'N/A'}
                  </span>
                )}
                <p className="text-xs text-on-surface-variant mt-2">
                  {bgpPct !== null ? `${bgpPct.toFixed(0)}% BGP` : 'No BGP data'}
                  {' + '}
                  {intfPct !== null ? `${intfPct.toFixed(0)}% Interfaces` : 'No interface data'}
                </p>
              </div>

              <div className="flex items-center gap-8 pb-2">
                <div className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded-full bg-secondary" />
                  <div>
                    <p className="text-xs text-on-surface-variant">BGP Up</p>
                    <p className="text-lg font-bold text-on-surface">{bgpUp}</p>
                  </div>
                </div>
                {bgpDown > 0 && (
                  <div className="flex items-center gap-2">
                    <span className="w-3 h-3 rounded-full bg-error" />
                    <div>
                      <p className="text-xs text-on-surface-variant">BGP Down</p>
                      <p className="text-lg font-bold text-error">{bgpDown}</p>
                    </div>
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded-full bg-primary" />
                  <div>
                    <p className="text-xs text-on-surface-variant">Interfaces</p>
                    <p className="text-lg font-bold text-on-surface">{intfUp}/{intfTotal}</p>
                  </div>
                </div>
                {criticalCount > 0 && (
                  <div className="flex items-center gap-2">
                    <span className="w-3 h-3 rounded-full bg-error animate-pulse" />
                    <div>
                      <p className="text-xs text-on-surface-variant">Critical</p>
                      <p className="text-lg font-bold text-error">{criticalCount}</p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Metric Cards */}
          <div className="grid grid-cols-4 gap-4">
            <MetricCard
              icon="router"
              label="Devices"
              value={totalDevices}
              sub={`${snappedDevices} with snapshots`}
            />
            <MetricCard
              icon="hub"
              label="BGP Established"
              value={bgpUp}
              sub={bgpTotal === 0 ? 'No sessions detected' : `of ${bgpTotal} total (${Math.round(bgpUp / bgpTotal * 100)}%)`}
              change={bgpDown > 0 ? `${bgpDown} down` : undefined}
              positive={false}
            />
            <MetricCard
              icon="lan"
              label="Interfaces Up"
              value={intfUp}
              sub={`of ${intfTotal} total (${intfTotal > 0 ? Math.round(intfUp / intfTotal * 100) : 0}%)`}
              change={intfDown > 0 ? `${intfDown} down` : undefined}
              positive={false}
            />
            <MetricCard
              icon="verified_user"
              label="Pending Approvals"
              value={approvalList.length}
              sub={approvalList.length > 0 ? 'Awaiting review' : 'Queue clear'}
            />
          </div>

          {/* Services health bar */}
          <div className="bg-surface-container-lowest rounded-xl shadow-sm px-6 py-4 flex items-center gap-6">
            <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant shrink-0">Services</p>
            <div className="flex items-center gap-3 flex-wrap">
              {Object.entries(deps).map(([name, info]) => {
                const ok = info?.status === 'ok' || info?.status === 'healthy';
                return (
                  <div key={name} className="flex items-center gap-1.5">
                    <span className={`w-2 h-2 rounded-full ${ok ? 'bg-secondary' : 'bg-error'}`} />
                    <span className="text-xs text-on-surface capitalize">{name}</span>
                  </div>
                );
              })}
            </div>
            <span className="ml-auto text-xs font-bold text-on-surface-variant">{servicesUp}/{servicesTotal} healthy</span>
          </div>
        </div>

        {/* Last Snapshot */}
        <div className="col-span-4">
          <LastSnapshotCard
            status={snapStatus}
            onTrigger={() => triggerSnapshot()}
          />
        </div>

        {/* Recent Alerts */}
        <div className="col-span-12 bg-surface-container-lowest rounded-xl shadow-sm p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1">
                Incident Feed
              </p>
              <h3 className="text-lg font-bold text-on-surface">Recent Findings</h3>
            </div>
            <div className="flex items-center gap-2">
              {[
                { key: null, label: 'All' },
                { key: 'high', label: 'High', variant: 'bg-error/10 text-error border-error/30' },
                { key: 'medium', label: 'Medium', variant: 'bg-tertiary/10 text-tertiary border-tertiary/30' },
                { key: 'low', label: 'Low', variant: 'bg-secondary/10 text-secondary border-secondary/30' },
              ].map((pill) => (
                <button
                  key={pill.label}
                  onClick={() => setFindingSevFilter(pill.key)}
                  className={`px-3 py-1 rounded-full text-xs font-bold border transition-colors ${
                    findingSevFilter === pill.key
                      ? pill.variant || 'bg-primary/10 text-primary border-primary/30'
                      : 'bg-surface-container-low text-on-surface-variant border-outline/20 hover:bg-surface-container-high'
                  }`}
                >
                  {pill.label}
                </button>
              ))}
            </div>
          </div>

          {filteredFindings.length > 0 ? (
            <div className="divide-y divide-outline-variant/30">
              {filteredFindings.map((finding) => (
                <AlertRow key={finding.id} finding={finding} />
              ))}
            </div>
          ) : (
            !loading && (
              <div className="flex flex-col items-center justify-center py-12 text-on-surface-variant">
                <Icon name="verified" className="text-5xl mb-2 text-secondary/40" />
                <p className="text-sm font-medium">No recent findings</p>
                <p className="text-xs">Run a snapshot and pipeline analysis to detect issues</p>
              </div>
            )
          )}

          {findingsList.length > 0 && (
            <a
              href="/insights"
              className="inline-flex items-center gap-1 text-primary text-sm font-semibold mt-4 hover:underline"
            >
              View All Insights
              <Icon name="arrow_forward" className="text-[16px]" />
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
