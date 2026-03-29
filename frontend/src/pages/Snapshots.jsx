import { useState, useEffect, useCallback } from 'react';
import { api } from '../api/client';
import Icon from '../components/Icon';
import StatusChip from '../components/StatusChip';

function timeAgo(dateStr) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function formatDuration(seconds) {
  if (!seconds) return '--';
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(0);
  return `${m}m ${s}s`;
}

function SnapshotRow({ snapshot, devices, isSelected, onSelect }) {
  const device = devices.find((d) => d.id === snapshot.device_id);
  const hostname = device?.hostname || snapshot.device_id.slice(0, 8);
  const hasError = snapshot.features_learned?.length === 0;

  return (
    <div
      onClick={() => onSelect(snapshot)}
      className={`grid grid-cols-[2fr_1.2fr_1fr_1fr_1fr_32px] gap-3 px-5 py-3.5 cursor-pointer transition-colors ${
        isSelected ? 'bg-primary/5' : 'hover:bg-blue-50/30'
      }`}
    >
      {/* Device */}
      <div className="flex items-center gap-3 min-w-0">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
          hasError ? 'bg-error/10' : 'bg-primary/10'
        }`}>
          <Icon
            name={device?.device_type === 'switch' ? 'lan' : device?.device_type === 'firewall' ? 'shield' : 'router'}
            className={`text-base ${hasError ? 'text-error' : 'text-primary'}`}
          />
        </div>
        <div className="min-w-0">
          <span className={`text-sm font-bold truncate block ${isSelected ? 'text-primary' : 'text-on-surface'}`}>
            {hostname}
          </span>
          <span className="text-[10px] text-on-surface-variant">{device?.management_ip || '--'}</span>
        </div>
      </div>

      {/* Time */}
      <div className="flex flex-col justify-center">
        <span className="text-xs text-on-surface">{timeAgo(snapshot.created_at)}</span>
        <span className="text-[10px] text-on-surface-variant">
          {new Date(snapshot.created_at).toLocaleString()}
        </span>
      </div>

      {/* Features */}
      <div className="flex items-center">
        <span className="text-xs text-on-surface font-mono">
          {snapshot.features_learned?.length || 0} features
        </span>
      </div>

      {/* Duration */}
      <div className="flex items-center">
        <span className="text-xs text-on-surface">{formatDuration(snapshot.duration_seconds)}</span>
      </div>

      {/* Status */}
      <div className="flex items-center">
        <StatusChip variant={hasError ? 'error' : 'success'} dot>
          {hasError ? 'FAILED' : 'OK'}
        </StatusChip>
      </div>

      {/* Chevron */}
      <div className="flex items-center justify-end">
        <Icon name="chevron_right" className="text-base text-outline" />
      </div>
    </div>
  );
}

const STATUS_STYLES = {
  added:   { icon: 'add_circle',    color: 'text-emerald-400', bg: 'bg-emerald-400/10', label: 'Added' },
  removed: { icon: 'remove_circle', color: 'text-red-400',     bg: 'bg-red-400/10',     label: 'Removed' },
  changed: { icon: 'change_circle', color: 'text-amber-400',   bg: 'bg-amber-400/10',   label: 'Changed' },
};

function DiffValue({ label, value, variant }) {
  const colors = variant === 'old'
    ? 'bg-red-500/10 border-red-500/20 text-red-300'
    : 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300';
  const formatted = typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
  return (
    <div className={`rounded-md border px-3 py-2 ${colors}`}>
      <span className="text-[9px] font-bold uppercase tracking-widest opacity-60 block mb-1">{label}</span>
      <pre className="font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all">{formatted}</pre>
    </div>
  );
}

function DiffEntry({ path, change }) {
  const style = STATUS_STYLES[change.status] || STATUS_STYLES.changed;
  return (
    <details className="group rounded-lg bg-slate-900 overflow-hidden">
      <summary className="flex items-center gap-2.5 px-4 py-2.5 cursor-pointer hover:bg-slate-800/60 transition-colors">
        <Icon name={style.icon} className={`text-base ${style.color}`} />
        <span className="flex-1 font-mono text-[11px] text-slate-300 truncate">{path}</span>
        <span className={`text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${style.bg} ${style.color}`}>
          {style.label}
        </span>
        <Icon name="expand_more" className="text-sm text-slate-500 group-open:rotate-180 transition-transform" />
      </summary>
      <div className="px-4 pb-3 pt-1 space-y-2">
        {change.status === 'changed' && (
          <>
            <DiffValue label="Old" value={change.old} variant="old" />
            <DiffValue label="New" value={change.new} variant="new" />
          </>
        )}
        {change.status === 'added' && (
          <DiffValue label="Value" value={change.value} variant="new" />
        )}
        {change.status === 'removed' && (
          <DiffValue label="Value" value={change.value} variant="old" />
        )}
      </div>
    </details>
  );
}

function SnapshotDetail({ snapshot, devices, onClose }) {
  const [tab, setTab] = useState('DATA');
  const [detail, setDetail] = useState(null);
  const [diff, setDiff] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [loadingDiff, setLoadingDiff] = useState(false);

  const device = devices.find((d) => d.id === snapshot.device_id);

  useEffect(() => {
    setLoadingDetail(true);
    api.snapshot(snapshot.id)
      .then(setDetail)
      .catch(() => {})
      .finally(() => setLoadingDetail(false));
  }, [snapshot.id]);

  useEffect(() => {
    if (tab === 'DIFF') {
      setLoadingDiff(true);
      api.snapshotDiff(snapshot.id)
        .then(setDiff)
        .catch(() => setDiff(null))
        .finally(() => setLoadingDiff(false));
    }
  }, [tab, snapshot.id]);

  const TABS = ['DATA', 'FEATURES', 'DIFF'];

  return (
    <div className="w-[480px] border-l border-outline/10 bg-surface-container-low shadow-[-4px_0_24px_rgba(0,0,0,0.04)] flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-5 pt-5 pb-4 border-b border-outline/10">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
            Snapshot Detail
          </span>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-surface-container-high transition-colors">
            <Icon name="close" className="text-lg text-on-surface-variant" />
          </button>
        </div>
        <h2 className="text-xl font-extrabold text-on-surface">{device?.hostname || 'Unknown'}</h2>
        <div className="flex items-center gap-3 mt-2">
          <span className="text-xs text-on-surface-variant">
            {new Date(snapshot.created_at).toLocaleString()}
          </span>
          <span className="text-xs text-on-surface-variant">&middot;</span>
          <span className="text-xs text-on-surface-variant">
            {formatDuration(snapshot.duration_seconds)}
          </span>
          <span className="text-xs text-on-surface-variant">&middot;</span>
          <span className="text-xs font-medium text-on-surface-variant capitalize">
            {snapshot.triggered_by}
          </span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex px-5 gap-5 border-b border-outline/10">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`py-3 text-xs font-bold transition-colors ${
              tab === t ? 'text-primary border-b-2 border-primary' : 'text-on-surface-variant hover:text-on-surface'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {tab === 'DATA' && (
          loadingDetail ? (
            <div className="flex items-center justify-center py-12">
              <div className="w-5 h-5 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
            </div>
          ) : detail?.snapshot_data ? (
            <div className="space-y-3">
              {Object.entries(detail.snapshot_data).map(([feature, data]) => {
                const isError = typeof data === 'object' && data?.error;
                const isString = typeof data === 'string';
                const size = JSON.stringify(data).length;
                return (
                  <details key={feature} className="group">
                    <summary className="flex items-center justify-between bg-surface-container-lowest rounded-lg px-4 py-3 cursor-pointer hover:bg-blue-50/30 transition-colors">
                      <div className="flex items-center gap-2.5">
                        <Icon
                          name={isError ? 'error_outline' : isString ? 'info' : 'check_circle'}
                          className={`text-base ${isError ? 'text-error' : isString ? 'text-on-surface-variant' : 'text-secondary'}`}
                        />
                        <span className="text-sm font-bold text-on-surface">{feature}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-on-surface-variant">
                          {isError ? 'error' : isString ? 'no data' : `${(size / 1024).toFixed(1)}KB`}
                        </span>
                        <Icon name="expand_more" className="text-base text-outline group-open:rotate-180 transition-transform" />
                      </div>
                    </summary>
                    <pre className="mt-2 bg-slate-900 rounded-lg p-3.5 font-mono text-[11px] text-slate-300 overflow-x-auto leading-relaxed max-h-64 overflow-y-auto">
                      {JSON.stringify(data, null, 2)}
                    </pre>
                  </details>
                );
              })}
            </div>
          ) : (
            <p className="text-sm text-on-surface-variant">No data available</p>
          )
        )}

        {tab === 'FEATURES' && (
          <div className="space-y-2">
            {(snapshot.features_learned || []).map((feat) => (
              <div key={feat} className="flex items-center gap-2.5 bg-surface-container-lowest rounded-lg px-4 py-3">
                <Icon name="check_circle" className="text-base text-secondary" />
                <span className="text-sm font-bold text-on-surface">{feat}</span>
              </div>
            ))}
            {(!snapshot.features_learned || snapshot.features_learned.length === 0) && (
              <div className="flex flex-col items-center py-8 text-on-surface-variant">
                <Icon name="warning" className="text-3xl mb-2 opacity-40" />
                <p className="text-xs font-semibold">No features learned</p>
                <p className="text-[10px] mt-1 opacity-60">This snapshot may have failed</p>
              </div>
            )}
          </div>
        )}

        {tab === 'DIFF' && (
          loadingDiff ? (
            <div className="flex items-center justify-center py-12">
              <div className="w-5 h-5 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
            </div>
          ) : diff ? (
            diff.previous_snapshot_id ? (
              <div className="space-y-2">
                {(() => {
                  const entries = Object.values(diff.changes);
                  const added = entries.filter((c) => c.status === 'added').length;
                  const removed = entries.filter((c) => c.status === 'removed').length;
                  const changed = entries.filter((c) => c.status === 'changed').length;
                  return (
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <Icon name="compare_arrows" className="text-base text-primary" />
                        <span className="text-xs text-on-surface-variant">
                          vs {diff.previous_snapshot_id.slice(0, 8)}
                        </span>
                      </div>
                      <div className="flex items-center gap-3">
                        {added > 0 && <span className="text-[10px] font-bold text-emerald-400">+{added} added</span>}
                        {removed > 0 && <span className="text-[10px] font-bold text-red-400">-{removed} removed</span>}
                        {changed > 0 && <span className="text-[10px] font-bold text-amber-400">~{changed} changed</span>}
                      </div>
                    </div>
                  );
                })()}
                {Object.keys(diff.changes).length === 0 ? (
                  <div className="flex flex-col items-center py-8 text-on-surface-variant">
                    <Icon name="check_circle" className="text-3xl mb-2 text-secondary opacity-60" />
                    <p className="text-xs font-semibold">No changes detected</p>
                  </div>
                ) : (
                  <div className="space-y-1.5 max-h-[calc(100vh-320px)] overflow-y-auto">
                    {Object.entries(diff.changes).map(([path, change]) => (
                      <DiffEntry key={path} path={path} change={change} />
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="flex flex-col items-center py-8 text-on-surface-variant">
                <Icon name="history" className="text-3xl mb-2 opacity-40" />
                <p className="text-xs font-semibold">No previous snapshot</p>
                <p className="text-[10px] mt-1 opacity-60">Take another snapshot to see changes</p>
              </div>
            )
          ) : (
            <p className="text-sm text-on-surface-variant">Failed to load diff</p>
          )
        )}
      </div>
    </div>
  );
}

export default function Snapshots() {
  const [snapshots, setSnapshots] = useState([]);
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [triggering, setTriggering] = useState(false);
  const [triggerDevice, setTriggerDevice] = useState('');
  const [filterDevice, setFilterDevice] = useState('');

  const fetchData = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([api.snapshots(), api.devices()])
      .then(([snaps, devs]) => {
        setSnapshots(snaps);
        setDevices(devs);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleTrigger = async () => {
    setTriggering(true);
    try {
      await api.triggerSnapshot(triggerDevice || undefined);
      setTriggerDevice('');
      fetchData();
    } catch (e) {
      setError(e);
    } finally {
      setTriggering(false);
    }
  };

  const filtered = filterDevice
    ? snapshots.filter((s) => s.device_id === filterDevice)
    : snapshots;

  return (
    <div className="flex h-full overflow-hidden">
      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 p-6 overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-extrabold text-on-surface">Snapshots</h1>
            <span className="flex items-center justify-center min-w-[28px] h-7 px-2 bg-surface-container-high rounded-full text-xs font-bold text-on-surface-variant">
              {filtered.length}
            </span>
          </div>

          <div className="flex items-center gap-3">
            {/* Device filter */}
            <select
              value={filterDevice}
              onChange={(e) => setFilterDevice(e.target.value)}
              className="px-3 py-2 rounded-lg border border-outline/20 text-xs font-bold text-on-surface-variant bg-surface-container-lowest focus:outline-none focus:ring-2 focus:ring-primary/30"
            >
              <option value="">All Devices</option>
              {devices.map((d) => (
                <option key={d.id} value={d.id}>{d.hostname}</option>
              ))}
            </select>

            {/* Trigger snapshot */}
            <div className="flex items-center gap-2">
              <select
                value={triggerDevice}
                onChange={(e) => setTriggerDevice(e.target.value)}
                className="px-3 py-2 rounded-lg border border-outline/20 text-xs font-bold text-on-surface-variant bg-surface-container-lowest focus:outline-none focus:ring-2 focus:ring-primary/30"
              >
                <option value="">All Devices</option>
                {devices.map((d) => (
                  <option key={d.id} value={d.id}>{d.hostname}</option>
                ))}
              </select>
              <button
                onClick={handleTrigger}
                disabled={triggering}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-white text-xs font-bold hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {triggering ? (
                  <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <Icon name="play_arrow" className="text-base" />
                )}
                {triggering ? 'Running...' : 'Take Snapshot'}
              </button>
            </div>
          </div>
        </div>

        {/* Stats cards */}
        {!loading && snapshots.length > 0 && (
          <div className="grid grid-cols-4 gap-4 mb-5">
            {[
              {
                label: 'Total Snapshots',
                value: snapshots.length,
                icon: 'camera',
                color: 'text-primary',
                bg: 'bg-primary/10',
              },
              {
                label: 'Devices Captured',
                value: new Set(snapshots.map((s) => s.device_id)).size,
                icon: 'router',
                color: 'text-secondary',
                bg: 'bg-secondary/10',
              },
              {
                label: 'Latest',
                value: snapshots.length > 0 ? timeAgo(snapshots[0].created_at) : '--',
                icon: 'schedule',
                color: 'text-tertiary',
                bg: 'bg-tertiary/10',
              },
              {
                label: 'Failed',
                value: snapshots.filter((s) => !s.features_learned?.length).length,
                icon: 'error_outline',
                color: 'text-error',
                bg: 'bg-error/10',
              },
            ].map((stat) => (
              <div key={stat.label} className="bg-surface-container-lowest rounded-xl px-5 py-4 flex items-center gap-4">
                <div className={`w-10 h-10 rounded-lg ${stat.bg} flex items-center justify-center`}>
                  <Icon name={stat.icon} className={`text-xl ${stat.color}`} />
                </div>
                <div>
                  <div className="text-lg font-extrabold text-on-surface">{stat.value}</div>
                  <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">{stat.label}</div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="flex items-center gap-3 bg-error/5 border border-error/20 rounded-xl px-5 py-4 mb-4">
            <Icon name="error" className="text-xl text-error" />
            <div>
              <p className="text-sm font-bold text-error">Error</p>
              <p className="text-xs text-on-surface-variant mt-0.5">{error.message}</p>
            </div>
            <button onClick={fetchData} className="ml-auto px-3 py-1.5 rounded-lg bg-error/10 text-error text-xs font-bold hover:bg-error/15 transition-colors">
              Retry
            </button>
          </div>
        )}

        {/* Table */}
        {!loading && !error && (
          <div className="bg-surface-container-lowest rounded-xl overflow-hidden">
            {/* Header */}
            <div className="grid grid-cols-[2fr_1.2fr_1fr_1fr_1fr_32px] gap-3 px-5 py-3 bg-surface-container-low border-b border-outline/10">
              {['Device', 'Taken', 'Features', 'Duration', 'Status'].map((h) => (
                <span key={h} className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
                  {h}
                </span>
              ))}
              <span />
            </div>

            {filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-on-surface-variant">
                <Icon name="camera" className="text-4xl mb-3 opacity-40" />
                <p className="text-sm font-semibold">No snapshots yet</p>
                <p className="text-xs mt-1 opacity-60">Take your first snapshot to see device state</p>
              </div>
            ) : (
              <div className="divide-y divide-outline/5">
                {filtered.map((snap) => (
                  <SnapshotRow
                    key={snap.id}
                    snapshot={snap}
                    devices={devices}
                    isSelected={selected?.id === snap.id}
                    onSelect={setSelected}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Detail panel */}
      {selected && (
        <SnapshotDetail
          snapshot={selected}
          devices={devices}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
