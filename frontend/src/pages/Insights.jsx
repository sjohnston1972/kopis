import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import { api } from '../api/client';
import Icon from '../components/Icon';
import StatusChip from '../components/StatusChip';

const severityColor = (severity) => {
  switch (severity?.toLowerCase()) {
    case 'critical':
    case 'high':
      return 'error';
    case 'medium':
      return 'tertiary';
    case 'low':
    case 'info':
    default:
      return 'secondary';
  }
};

const severityIcon = (severity) => {
  switch (severity?.toLowerCase()) {
    case 'critical':
      return 'crisis_alert';
    case 'high':
      return 'warning';
    case 'medium':
      return 'info';
    case 'low':
      return 'check_circle';
    default:
      return 'auto_awesome';
  }
};

const severityChipVariant = (severity) => {
  switch (severity?.toLowerCase()) {
    case 'critical':
    case 'high':
      return 'error';
    case 'medium':
      return 'neutral';
    case 'low':
    case 'info':
    default:
      return 'success';
  }
};

const severityLabel = (severity) => {
  switch (severity?.toLowerCase()) {
    case 'critical':
      return 'CRITICAL';
    case 'high':
      return 'HIGH';
    case 'medium':
      return 'ADVISORY';
    case 'low':
      return 'LOW';
    case 'info':
      return 'INFO';
    default:
      return severity?.toUpperCase() || 'UNKNOWN';
  }
};

const btnColor = (severity) => {
  const color = severityColor(severity);
  switch (color) {
    case 'error':
      return 'bg-error hover:bg-error/90 text-on-error';
    case 'tertiary':
      return 'bg-tertiary hover:bg-tertiary/90 text-on-tertiary';
    case 'secondary':
    default:
      return 'bg-secondary hover:bg-secondary/90 text-on-secondary';
  }
};

const iconCircleBg = (severity) => {
  const color = severityColor(severity);
  switch (color) {
    case 'error':
      return 'bg-error/10 text-error';
    case 'tertiary':
      return 'bg-tertiary/10 text-tertiary';
    case 'secondary':
    default:
      return 'bg-secondary/10 text-secondary';
  }
};

function formatTimeAgo(dateStr) {
  if (!dateStr) return 'just now';
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function formatTimeShort(dateStr) {
  if (!dateStr) return '--:--';
  const d = new Date(dateStr);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export default function Insights() {
  const { data: findings, loading, error, refetch } = useApi(() => api.findings(), []);
  const [openMenu, setOpenMenu] = useState(null);

  const items = findings || [];
  const remediationItems = items.filter((f) => f.requires_remediation);
  const criticalCount = items.filter(
    (f) => f.severity?.toLowerCase() === 'critical' || f.severity?.toLowerCase() === 'high',
  ).length;
  const nodesAnalyzed = new Set(items.map((f) => f.device_id)).size;
  const riskScore = items.length === 0
    ? 0
    : Math.min(
        100,
        Math.round(
          items.reduce((acc, f) => {
            const s = f.severity?.toLowerCase();
            if (s === 'critical') return acc + 25;
            if (s === 'high') return acc + 15;
            if (s === 'medium') return acc + 5;
            return acc + 1;
          }, 0),
        ),
      );
  const efficiency = items.length === 0 ? 99.8 : Math.max(85, 99.8 - criticalCount * 2.1).toFixed(1);
  const automationConfidence = items.length === 0 ? 94 : Math.max(60, 94 - criticalCount * 5);

  const handleRescan = () => {
    api.pipelineRun({}).then(() => refetch());
  };

  return (
    <div className="min-h-screen bg-surface p-6 lg:p-10">
      {/* Page Header */}
      <header className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between mb-8">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="w-2.5 h-2.5 rounded-full bg-secondary animate-pulse" />
            <span className="text-sm font-semibold text-secondary">System Status: Optimal</span>
          </div>
          <h1 className="text-4xl font-extrabold tracking-tight text-on-surface">AI Insights Panel</h1>
          <p className="mt-1 text-on-surface-variant text-sm max-w-xl">
            Advanced neural analysis of your global infrastructure — real-time threat detection, anomaly
            classification, and autonomous remediation proposals.
          </p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <button className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg border border-outline/30 text-sm font-semibold text-on-surface-variant hover:bg-surface-container-high transition-colors">
            <Icon name="history" className="text-lg" />
            Audit Log
          </button>
          <button
            onClick={handleRescan}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-gradient-to-br from-primary to-primary-container text-on-primary text-sm font-semibold shadow-lg shadow-primary/20 hover:shadow-primary/30 transition-all"
          >
            <Icon name="radar" className="text-lg" />
            Re-scan Network
          </button>
        </div>
      </header>

      {/* Loading / Error */}
      {loading && (
        <div className="flex items-center justify-center py-24">
          <div className="w-8 h-8 border-3 border-primary/20 border-t-primary rounded-full animate-spin" />
        </div>
      )}
      {error && (
        <div className="rounded-xl bg-error/5 border border-error/20 p-4 mb-6 flex items-center gap-3">
          <Icon name="error" className="text-error" />
          <span className="text-sm text-error font-medium">Failed to load findings: {error.message}</span>
          <button onClick={refetch} className="ml-auto text-sm font-semibold text-error underline">
            Retry
          </button>
        </div>
      )}

      {!loading && !error && (
        <div className="grid grid-cols-12 gap-6">
          {/* ===== LEFT COLUMN (col-span-8) ===== */}
          <div className="col-span-12 lg:col-span-8 flex flex-col gap-6">
            {/* Executive Summary */}
            <div className="bg-surface-container-lowest rounded-xl shadow-sm border border-outline/10 p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-full bg-secondary/10 flex items-center justify-center">
                  <Icon name="auto_awesome" className="text-secondary text-xl" fill />
                </div>
                <h2 className="text-lg font-bold text-on-surface">Executive Summary</h2>
              </div>
              <p className="text-sm text-on-surface-variant leading-relaxed mb-5">
                Network infrastructure is operating at{' '}
                <span className="font-bold text-secondary">{efficiency}% efficiency</span>. Analysis has identified{' '}
                <span className={`font-bold ${criticalCount > 0 ? 'text-error' : 'text-secondary'}`}>
                  {items.length} issue{items.length !== 1 ? 's' : ''}
                </span>{' '}
                across monitored nodes
                {criticalCount > 0 && (
                  <>
                    , including{' '}
                    <span className="font-bold text-error">
                      {criticalCount} critical/high severity finding{criticalCount !== 1 ? 's' : ''}
                    </span>
                  </>
                )}
                . {remediationItems.length} remediation{remediationItems.length !== 1 ? 's' : ''}{' '}
                {remediationItems.length === 1 ? 'is' : 'are'} queued for review.
              </p>
              <div className="grid grid-cols-3 gap-4">
                <div className="border-l-4 border-error rounded-lg bg-error/5 p-4">
                  <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-1">
                    Risk Score
                  </p>
                  <p className="text-2xl font-extrabold text-error">{riskScore}</p>
                  <p className="text-xs text-on-surface-variant">/ 100</p>
                </div>
                <div className="border-l-4 border-primary rounded-lg bg-primary/5 p-4">
                  <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-1">
                    Nodes Analyzed
                  </p>
                  <p className="text-2xl font-extrabold text-primary">{nodesAnalyzed}</p>
                  <p className="text-xs text-on-surface-variant">devices</p>
                </div>
                <div className="border-l-4 border-secondary rounded-lg bg-secondary/5 p-4">
                  <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-1">
                    Remediations Ready
                  </p>
                  <p className="text-2xl font-extrabold text-secondary">{remediationItems.length}</p>
                  <p className="text-xs text-on-surface-variant">pending approval</p>
                </div>
              </div>
            </div>

            {/* Risk Detection Grid */}
            <div>
              <h2 className="text-lg font-bold text-on-surface mb-4">Risk Detection</h2>
              {items.length === 0 ? (
                <div className="bg-surface-container-lowest rounded-xl border border-outline/10 p-10 text-center">
                  <Icon name="verified" className="text-4xl text-secondary mb-2" />
                  <p className="text-sm text-on-surface-variant">No findings detected. Infrastructure looks clean.</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {items.map((finding) => (
                    <div
                      key={finding.id}
                      className="bg-surface-container-lowest rounded-xl border border-outline/10 p-5 hover:shadow-md transition-shadow relative group"
                    >
                      <div className="flex items-start gap-3 mb-3">
                        <div
                          className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 ${iconCircleBg(finding.severity)}`}
                        >
                          <Icon name={severityIcon(finding.severity)} className="text-lg" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <StatusChip variant={severityChipVariant(finding.severity)} dot>
                              {severityLabel(finding.severity)}
                            </StatusChip>
                            {finding.category && (
                              <span className="text-[10px] font-medium text-on-surface-variant bg-surface-container-high px-2 py-0.5 rounded-full uppercase">
                                {finding.category}
                              </span>
                            )}
                          </div>
                          <h3 className="text-lg font-bold text-on-surface truncate">{finding.title}</h3>
                        </div>
                      </div>
                      <p className="text-sm text-on-surface-variant leading-relaxed mb-4 line-clamp-2">
                        {finding.description}
                      </p>
                      <div className="flex items-center justify-between">
                        <button
                          className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold transition-colors ${btnColor(finding.severity)}`}
                        >
                          <Icon name="open_in_new" className="text-sm" />
                          Investigate
                        </button>
                        <div className="relative">
                          <button
                            onClick={() => setOpenMenu(openMenu === finding.id ? null : finding.id)}
                            className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-surface-container-high text-on-surface-variant transition-colors"
                          >
                            <Icon name="more_vert" className="text-lg" />
                          </button>
                          {openMenu === finding.id && (
                            <div className="absolute right-0 top-full mt-1 w-40 bg-surface-container-lowest rounded-lg shadow-lg border border-outline/10 py-1 z-10">
                              <button className="w-full text-left px-3 py-2 text-sm text-on-surface hover:bg-surface-container-high transition-colors">
                                View Details
                              </button>
                              <button className="w-full text-left px-3 py-2 text-sm text-on-surface hover:bg-surface-container-high transition-colors">
                                Dismiss
                              </button>
                              <button className="w-full text-left px-3 py-2 text-sm text-error hover:bg-error/5 transition-colors">
                                Escalate
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                      {finding.affected_entity && (
                        <p className="mt-3 text-[11px] text-on-surface-variant font-mono bg-surface-container-low rounded px-2 py-1 truncate">
                          {finding.affected_entity}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* ===== RIGHT SIDEBAR (col-span-4) ===== */}
          <div className="col-span-12 lg:col-span-4 flex flex-col gap-6">
            {/* Suggested Actions */}
            <div className="glass-panel rounded-xl border border-outline/10 p-5">
              <div className="flex items-center gap-2 mb-4">
                <Icon name="bolt" className="text-primary text-xl" fill />
                <h2 className="text-base font-bold text-on-surface">Suggested Actions</h2>
              </div>
              {remediationItems.length === 0 ? (
                <p className="text-sm text-on-surface-variant py-4 text-center">
                  No remediation actions pending.
                </p>
              ) : (
                <ul className="space-y-3">
                  {remediationItems.map((item) => (
                    <li
                      key={item.id}
                      className="flex items-start gap-3 p-3 rounded-lg hover:bg-surface-container-low transition-colors"
                    >
                      <div className="w-8 h-8 rounded-full bg-surface-container-lowest border border-outline/20 flex items-center justify-center shrink-0">
                        <Icon
                          name={severityIcon(item.severity)}
                          className={`text-sm ${
                            severityColor(item.severity) === 'error'
                              ? 'text-error'
                              : severityColor(item.severity) === 'tertiary'
                                ? 'text-tertiary'
                                : 'text-secondary'
                          }`}
                        />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-on-surface truncate">{item.title}</p>
                        <p className="text-xs text-on-surface-variant line-clamp-2 mt-0.5">{item.description}</p>
                        <button className="mt-1.5 text-xs font-bold text-primary hover:text-primary-container transition-colors">
                          Apply &rarr;
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}

              {/* Automation Confidence */}
              <div className="mt-5 pt-4 border-t border-outline/10">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide">
                    Automation Confidence
                  </span>
                  <span className="text-xs font-bold text-secondary">{automationConfidence}%</span>
                </div>
                <div className="w-full h-2 bg-surface-container-high rounded-full overflow-hidden">
                  <div
                    className="h-full bg-secondary rounded-full transition-all duration-700 ease-out"
                    style={{ width: `${automationConfidence}%` }}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* ===== ANOMALIES TIMELINE (full width) ===== */}
          <div className="col-span-12 mt-2">
            <div className="flex items-center gap-3 mb-4">
              <h2 className="text-lg font-bold text-on-surface whitespace-nowrap">Anomalies Timeline</h2>
              <hr className="flex-1 border-outline/20" />
            </div>

            {items.length === 0 ? (
              <p className="text-sm text-on-surface-variant text-center py-6">No anomalies to display.</p>
            ) : (
              <div className="space-y-3">
                {items.slice(0, 10).map((finding) => {
                  const color = severityColor(finding.severity);
                  const dotClass =
                    color === 'error'
                      ? 'bg-error'
                      : color === 'tertiary'
                        ? 'bg-tertiary'
                        : 'bg-secondary';
                  return (
                    <div key={`tl-${finding.id}`} className="grid grid-cols-12 gap-3 items-start">
                      {/* Time */}
                      <div className="col-span-2 text-right">
                        <span className="text-xs font-mono text-on-surface-variant">
                          {formatTimeShort(finding.created_at)}
                        </span>
                        <span className="block text-[10px] text-outline">
                          {formatTimeAgo(finding.created_at)}
                        </span>
                      </div>
                      {/* Dot */}
                      <div className="col-span-1 flex justify-center pt-1.5">
                        <span className={`w-3 h-3 rounded-full ${dotClass} ring-4 ring-surface`} />
                      </div>
                      {/* Event Card */}
                      <div className="col-span-9 bg-surface-container-low rounded-lg p-4 hover:bg-surface-container-high transition-colors cursor-pointer group">
                        <div className="flex items-center gap-2 mb-1">
                          <StatusChip variant={severityChipVariant(finding.severity)} dot>
                            {severityLabel(finding.severity)}
                          </StatusChip>
                          {finding.affected_entity && (
                            <span className="text-[10px] font-mono text-on-surface-variant">
                              {finding.affected_entity}
                            </span>
                          )}
                        </div>
                        <h4 className="text-sm font-semibold text-on-surface group-hover:text-primary transition-colors">
                          {finding.title}
                        </h4>
                        <p className="text-xs text-on-surface-variant mt-0.5 line-clamp-1">
                          {finding.description}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
