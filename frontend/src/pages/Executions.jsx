import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import { api } from '../api/client';
import Icon from '../components/Icon';
import StatusChip from '../components/StatusChip';

function statusToChip(entry) {
  const status = entry.status?.toLowerCase();
  const result = entry.execution_result;
  const success = result && !result.error && result.success !== false;

  if (status === 'executed' || status === 'success') {
    if (result && !success) {
      return <StatusChip variant="error">FAILED</StatusChip>;
    }
    return <StatusChip variant="success">SUCCESS</StatusChip>;
  }
  if (status === 'failed') {
    return <StatusChip variant="error">FAILED</StatusChip>;
  }
  if (status === 'approved') {
    return <StatusChip variant="info">APPROVED</StatusChip>;
  }
  if (status === 'denied') {
    return <StatusChip variant="neutral">DENIED</StatusChip>;
  }
  return <StatusChip variant="neutral">{(status || 'UNKNOWN').toUpperCase()}</StatusChip>;
}

function formatTimestamp(ts) {
  if (!ts) return '\u2014';
  try {
    const date = new Date(ts);
    const now = new Date();
    const diffMs = now - date;
    const diffMin = Math.floor(diffMs / 60000);
    const diffHr = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHr / 24);

    if (diffMin < 1) return 'Just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHr < 24) return `${diffHr}h ago`;
    if (diffDay < 7) return `${diffDay}d ago`;
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return ts;
  }
}

function resultSummary(entry) {
  const result = entry.execution_result;
  if (!result) return '\u2014';
  if (typeof result === 'string') return result;
  if (result.summary) return result.summary;
  if (result.error) return result.error;
  if (result.output) return typeof result.output === 'string' ? result.output : JSON.stringify(result.output);
  return '\u2014';
}

export default function Executions() {
  const { data: history, loading, error } = useApi(() => api.approvalHistory());

  const entries = history || [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-4xl font-extrabold text-on-surface">Execution Log</h1>
        <p className="mt-1 text-sm text-on-surface-variant">
          History of approved remediations and their outcomes
        </p>
      </div>

      {/* Error state */}
      {error && (
        <div className="bg-error/10 text-error rounded-xl px-4 py-3 text-sm">
          Failed to load execution history: {error.message}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center py-20 text-on-surface-variant">
          <Icon name="progress_activity" className="text-3xl animate-spin" />
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && entries.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <Icon name="history" className="text-5xl text-outline" />
          <p className="text-lg font-semibold text-on-surface">No execution history</p>
          <p className="text-sm text-on-surface-variant">
            Approved remediations will appear here after execution
          </p>
        </div>
      )}

      {/* History table */}
      {!loading && entries.length > 0 && (
        <div className="bg-surface-container-lowest rounded-xl overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-surface-container-low">
                <th className="text-left px-5 py-3 text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
                  Action
                </th>
                <th className="text-left px-5 py-3 text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
                  Device
                </th>
                <th className="text-left px-5 py-3 text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
                  Status
                </th>
                <th className="text-left px-5 py-3 text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
                  Executed
                </th>
                <th className="text-left px-5 py-3 text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
                  Result
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-container-high">
              {entries.map((entry) => {
                const recommendation = entry.recommendation || {};
                const device = entry.device || {};

                return (
                  <tr key={entry.id} className="hover:bg-surface-container-low/50 transition-colors">
                    <td className="px-5 py-4 text-sm text-on-surface max-w-xs truncate">
                      {recommendation.action_description || recommendation.action || '\u2014'}
                    </td>
                    <td className="px-5 py-4 text-sm text-on-surface-variant whitespace-nowrap">
                      {device.hostname || '\u2014'}
                    </td>
                    <td className="px-5 py-4">
                      {statusToChip(entry)}
                    </td>
                    <td className="px-5 py-4 text-sm text-on-surface-variant whitespace-nowrap">
                      {formatTimestamp(entry.executed_at || entry.approved_at)}
                    </td>
                    <td className="px-5 py-4 text-sm text-on-surface-variant max-w-sm truncate">
                      {resultSummary(entry)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
