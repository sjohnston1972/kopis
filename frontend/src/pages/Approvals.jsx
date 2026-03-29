import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import { api } from '../api/client';
import Icon from '../components/Icon';
import StatusChip from '../components/StatusChip';

const severityVariant = (severity) => {
  switch (severity?.toUpperCase()) {
    case 'CRITICAL':
    case 'HIGH':
      return 'error';
    case 'MEDIUM':
      return 'neutral';
    case 'LOW':
      return 'success';
    default:
      return 'neutral';
  }
};

function ApprovalCard({ approval, onApprove, onDeny }) {
  const [notes, setNotes] = useState('');
  const [showNotes, setShowNotes] = useState(false);
  const [acting, setActing] = useState(false);

  const finding = approval.finding || {};
  const recommendation = approval.recommendation || {};
  const device = approval.device || {};
  const commands = recommendation.commands || [];
  const rollbackCommands = recommendation.rollback_commands || [];

  const handleApprove = async () => {
    setActing(true);
    try {
      await onApprove(approval.id, { notes });
    } finally {
      setActing(false);
    }
  };

  const handleDeny = async () => {
    setActing(true);
    try {
      await onDeny(approval.id, { notes });
    } finally {
      setActing(false);
    }
  };

  return (
    <div className="bg-surface-container-lowest rounded-xl p-6 space-y-4">
      {/* Top row: finding title + severity */}
      <div className="flex items-start justify-between gap-4">
        <h3 className="text-lg font-bold text-on-surface leading-tight">
          {finding.title || 'Untitled Finding'}
        </h3>
        <StatusChip variant={severityVariant(finding.severity)}>
          {(finding.severity || 'UNKNOWN').toUpperCase()}
        </StatusChip>
      </div>

      {/* Device info */}
      <div className="flex items-center gap-4 text-sm text-on-surface-variant">
        <span className="inline-flex items-center gap-1.5">
          <Icon name="dns" className="text-[18px]" />
          {device.hostname || 'Unknown device'}
        </span>
        {finding.affected_entity && (
          <span className="inline-flex items-center gap-1.5">
            <Icon name="settings_ethernet" className="text-[18px]" />
            {finding.affected_entity}
          </span>
        )}
      </div>

      {/* Recommended action */}
      <p className="text-sm text-on-surface">
        {recommendation.action_description || recommendation.action || 'No action description'}
      </p>

      {/* Commands block */}
      {commands.length > 0 && (
        <div className="bg-slate-900 rounded-lg p-4 overflow-x-auto">
          <pre className="font-mono text-[11px] text-slate-300 leading-relaxed whitespace-pre">
            {commands.map((cmd, i) => (
              <span key={i}>
                {cmd}
                {i < commands.length - 1 ? '\n' : ''}
              </span>
            ))}
          </pre>
        </div>
      )}

      {/* Risk + rollback info */}
      <div className="flex items-center gap-3 flex-wrap">
        {recommendation.risk_level && (
          <StatusChip
            variant={
              recommendation.risk_level === 'high'
                ? 'error'
                : recommendation.risk_level === 'medium'
                  ? 'warning'
                  : 'success'
            }
          >
            {recommendation.risk_level.toUpperCase()} RISK
          </StatusChip>
        )}
        {rollbackCommands.length > 0 && (
          <span className="text-xs text-on-surface-variant inline-flex items-center gap-1">
            <Icon name="undo" className="text-[14px]" />
            {rollbackCommands.length} rollback command{rollbackCommands.length !== 1 ? 's' : ''} available
          </span>
        )}
      </div>

      {/* Jira link */}
      {approval.jira_key && (
        <a
          href={approval.jira_url || '#'}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline"
        >
          <Icon name="open_in_new" className="text-[14px]" />
          {approval.jira_key}
        </a>
      )}

      {/* Notes toggle */}
      {showNotes && (
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Optional notes..."
          rows={2}
          className="w-full rounded-lg border border-outline/30 bg-surface-container-low px-3 py-2 text-sm text-on-surface placeholder:text-on-surface-variant/50 focus:outline-none focus:ring-2 focus:ring-primary/40 resize-none"
        />
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-3 pt-2">
        <button
          onClick={handleDeny}
          disabled={acting}
          className="px-4 py-2 rounded-lg bg-error/10 text-error text-sm font-semibold hover:bg-error/20 transition-colors disabled:opacity-50"
        >
          Deny
        </button>
        <button
          onClick={handleApprove}
          disabled={acting}
          className="px-4 py-2 rounded-lg bg-gradient-to-br from-primary to-primary-container text-white text-sm font-semibold hover:shadow-lg hover:shadow-primary/20 transition-all disabled:opacity-50"
        >
          Approve
        </button>
        <button
          onClick={() => setShowNotes(!showNotes)}
          className="ml-auto text-xs text-on-surface-variant hover:text-on-surface transition-colors"
        >
          {showNotes ? 'Hide notes' : 'Add notes'}
        </button>
      </div>
    </div>
  );
}

export default function Approvals() {
  const { data: approvals, loading, error, refetch } = useApi(() => api.approvals());
  const [expiring, setExpiring] = useState(false);

  const pending = (approvals || []).filter((a) => a.status === 'pending');

  const handleApprove = async (id, body) => {
    await api.approve(id, body);
    refetch();
  };

  const handleDeny = async (id, body) => {
    await api.deny(id, body);
    refetch();
  };

  const handleExpire = async () => {
    setExpiring(true);
    try {
      await api.expireApprovals();
      refetch();
    } finally {
      setExpiring(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-4">
          <h1 className="text-4xl font-extrabold text-on-surface">Approval Queue</h1>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-secondary animate-pulse" />
            <span className="text-sm font-medium text-on-surface-variant">Pending Review</span>
            <span className="inline-flex items-center justify-center min-w-[24px] h-6 px-1.5 rounded-full bg-primary/10 text-primary text-xs font-bold">
              {loading ? '--' : pending.length}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExpire}
            disabled={expiring}
            className="px-4 py-2 rounded-lg border border-outline/30 text-sm font-semibold text-on-surface-variant hover:bg-surface-container-high transition-colors disabled:opacity-50"
          >
            Expire Stale
          </button>
          <a
            href="/executions"
            className="px-4 py-2 rounded-lg border border-outline/30 text-sm font-semibold text-on-surface-variant hover:bg-surface-container-high transition-colors"
          >
            View History
          </a>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="bg-error/10 text-error rounded-xl px-4 py-3 text-sm">
          Failed to load approvals: {error.message}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center py-20 text-on-surface-variant">
          <Icon name="progress_activity" className="text-3xl animate-spin" />
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && pending.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <Icon name="check_circle" className="text-5xl text-secondary" fill />
          <p className="text-lg font-semibold text-on-surface">All clear</p>
          <p className="text-sm text-on-surface-variant">No pending approvals</p>
        </div>
      )}

      {/* Pending approvals list */}
      {!loading && pending.length > 0 && (
        <div className="space-y-4">
          {pending.map((approval) => (
            <ApprovalCard
              key={approval.id}
              approval={approval}
              onApprove={handleApprove}
              onDeny={handleDeny}
            />
          ))}
        </div>
      )}
    </div>
  );
}
