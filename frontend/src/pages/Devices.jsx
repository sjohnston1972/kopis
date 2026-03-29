import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import { api } from '../api/client';
import Icon from '../components/Icon';
import StatusChip from '../components/StatusChip';

const FILTERS = ['ALL', 'ACTIVE', 'ISSUES'];

const TABS = ['CONFIG', 'INTERFACES', 'HEALTH'];

const SAMPLE_CONFIG = `hostname R1-CORE
!
interface GigabitEthernet0/0
 ip address 10.0.0.1 255.255.255.0
 no shutdown
!
router ospf 1
 network 10.0.0.0 0.0.0.255 area 0
!
line vty 0 4
 transport input ssh
!`;

function getComplianceInfo(device) {
  const tags = device.tags || {};
  if (tags.compliance === 'critical') {
    return { label: 'Critical', color: 'error', pct: 25 };
  }
  if (tags.compliance === 'vulnerable') {
    return { label: 'Vulnerable', color: 'tertiary-container', pct: 60 };
  }
  return { label: 'Compliant', color: 'secondary', pct: 100 };
}

function getDeviceStatus(device) {
  const lastSeen = device.last_seen;
  if (!lastSeen) return 'OFFLINE';
  const diff = Date.now() - new Date(lastSeen).getTime();
  // Consider offline if not seen in 30 minutes
  return diff < 30 * 60 * 1000 ? 'ONLINE' : 'OFFLINE';
}

function filterDevices(devices, filter) {
  if (filter === 'ALL') return devices;
  if (filter === 'ACTIVE') return devices.filter((d) => getDeviceStatus(d) === 'ONLINE');
  if (filter === 'ISSUES') {
    return devices.filter((d) => {
      const c = getComplianceInfo(d);
      return c.label === 'Critical' || c.label === 'Vulnerable';
    });
  }
  return devices;
}

function DeviceTable({ devices, selectedDevice, onSelect }) {
  return (
    <div className="bg-surface-container-lowest rounded-xl overflow-hidden">
      {/* Table header */}
      <div className="grid grid-cols-[2fr_1fr_1fr_1.2fr_1fr_1.2fr_32px] gap-3 px-5 py-3 bg-surface-container-low border-b border-outline/10">
        {['Hostname', 'Status', 'Role', 'IP Address', 'Software', 'Compliance'].map((h) => (
          <span key={h} className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
            {h}
          </span>
        ))}
        <span />
      </div>

      {/* Table rows */}
      {devices.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-on-surface-variant">
          <Icon name="dns" className="text-4xl mb-3 opacity-40" />
          <p className="text-sm font-semibold">No devices found</p>
          <p className="text-xs mt-1 opacity-60">Add a device or refresh inventory from Grafana</p>
        </div>
      ) : (
        <div className="divide-y divide-outline/5">
          {devices.map((device) => {
            const isSelected = selectedDevice?.id === device.id;
            const status = getDeviceStatus(device);
            const compliance = getComplianceInfo(device);
            return (
              <div
                key={device.id}
                onClick={() => onSelect(device)}
                className={`grid grid-cols-[2fr_1fr_1fr_1.2fr_1fr_1.2fr_32px] gap-3 px-5 py-3.5 cursor-pointer transition-colors ${
                  isSelected ? 'bg-primary/5' : 'hover:bg-blue-50/30'
                }`}
              >
                {/* Hostname */}
                <div className="flex flex-col justify-center min-w-0">
                  <span className={`text-sm font-bold truncate ${isSelected ? 'text-primary' : 'text-on-surface'}`}>
                    {device.hostname}
                  </span>
                  <span className="text-[11px] text-on-surface-variant truncate">
                    {device.tags?.model || device.platform || '--'}
                  </span>
                </div>

                {/* Status */}
                <div className="flex items-center">
                  <StatusChip
                    variant={status === 'ONLINE' ? 'success' : 'error'}
                    dot
                    pulse={status === 'ONLINE'}
                  >
                    {status}
                  </StatusChip>
                </div>

                {/* Role */}
                <div className="flex items-center">
                  <span className="text-xs text-on-surface capitalize">{device.device_type || '--'}</span>
                </div>

                {/* IP Address */}
                <div className="flex items-center">
                  <span className="text-xs text-on-surface font-mono">{device.management_ip || '--'}</span>
                </div>

                {/* Software */}
                <div className="flex items-center">
                  <span className="text-xs text-on-surface">{device.platform || '--'}</span>
                </div>

                {/* Compliance */}
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1.5 bg-outline/10 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        compliance.color === 'secondary'
                          ? 'bg-secondary'
                          : compliance.color === 'error'
                          ? 'bg-error'
                          : 'bg-tertiary'
                      }`}
                      style={{ width: `${compliance.pct}%` }}
                    />
                  </div>
                  <span
                    className={`text-[10px] font-bold whitespace-nowrap ${
                      compliance.color === 'secondary'
                        ? 'text-secondary'
                        : compliance.color === 'error'
                        ? 'text-error'
                        : 'text-tertiary'
                    }`}
                  >
                    {compliance.label}
                  </span>
                </div>

                {/* Chevron */}
                <div className="flex items-center justify-end">
                  <Icon name="chevron_right" className="text-base text-outline" />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function DetailPanel({ device, onClose }) {
  const [activeTab, setActiveTab] = useState('CONFIG');
  const [copied, setCopied] = useState(false);
  const status = getDeviceStatus(device);
  const compliance = getComplianceInfo(device);

  const handleCopy = () => {
    navigator.clipboard.writeText(SAMPLE_CONFIG).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="w-96 border-l border-outline/10 bg-surface-container-low shadow-[-4px_0_24px_rgba(0,0,0,0.04)] flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-5 pt-5 pb-4 border-b border-outline/10">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
            {device.device_type || 'Device'}
          </span>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-surface-container-high transition-colors"
          >
            <Icon name="close" className="text-lg text-on-surface-variant" />
          </button>
        </div>
        <h2 className="text-xl font-extrabold text-on-surface">{device.hostname}</h2>
        <div className="flex items-center gap-2 mt-1.5">
          <span
            className={`w-2 h-2 rounded-full ${
              status === 'ONLINE' ? 'bg-secondary animate-pulse' : 'bg-error'
            }`}
          />
          <span className="text-xs text-on-surface-variant">
            {device.tags?.model || device.platform || '--'} &middot; {device.management_ip}
          </span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex px-5 gap-5 border-b border-outline/10">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`py-3 text-xs font-bold transition-colors ${
              activeTab === tab
                ? 'text-primary border-b-2 border-primary'
                : 'text-on-surface-variant hover:text-on-surface'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {activeTab === 'CONFIG' && (
          <>
            {/* Running Config */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
                  Running Config
                </span>
                <button
                  onClick={handleCopy}
                  className="flex items-center gap-1 text-[10px] font-bold text-primary hover:text-primary/80 transition-colors"
                >
                  <Icon name={copied ? 'check' : 'content_copy'} className="text-sm" />
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
              <pre className="bg-slate-900 rounded-lg p-3.5 font-mono text-[11px] text-slate-300 overflow-x-auto leading-relaxed max-h-48 overflow-y-auto">
                {SAMPLE_CONFIG}
              </pre>
            </div>

            {/* Quick Metrics */}
            <div>
              <span className="text-[10px] font-extrabold uppercase tracking-widest text-on-surface-variant">
                Quick Metrics
              </span>
              <div className="grid grid-cols-2 gap-2 mt-2">
                {[
                  { label: 'CPU Load', value: '12%', icon: 'memory' },
                  { label: 'Uptime', value: '47d 8h', icon: 'schedule' },
                  { label: 'Temp', value: '42 C', icon: 'thermostat' },
                  { label: 'Errors', value: '0', icon: 'error_outline' },
                ].map((m) => (
                  <div
                    key={m.label}
                    className="flex items-center gap-2.5 bg-surface-container-lowest rounded-lg px-3 py-2.5"
                  >
                    <Icon name={m.icon} className="text-base text-on-surface-variant" />
                    <div>
                      <div className="text-xs font-bold text-on-surface">{m.value}</div>
                      <div className="text-[10px] text-on-surface-variant">{m.label}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Compliance banner */}
            <div className="flex items-center gap-3 bg-secondary/5 rounded-lg px-4 py-3">
              <Icon name="verified_user" className="text-xl text-secondary" fill />
              <div>
                <div className="text-xs font-bold text-on-surface">{compliance.label}</div>
                <div className="text-[10px] text-on-surface-variant">
                  Last audit {device.last_refreshed ? new Date(device.last_refreshed).toLocaleDateString() : 'N/A'}
                </div>
              </div>
            </div>
          </>
        )}

        {activeTab === 'INTERFACES' && (
          <div className="space-y-2">
            {['GigabitEthernet0/0', 'GigabitEthernet0/1', 'Loopback0'].map((intf, i) => (
              <div key={intf} className="flex items-center justify-between bg-surface-container-lowest rounded-lg px-4 py-3">
                <div className="flex items-center gap-2.5">
                  <Icon name="lan" className="text-base text-on-surface-variant" />
                  <div>
                    <div className="text-xs font-bold text-on-surface">{intf}</div>
                    <div className="text-[10px] text-on-surface-variant">
                      {i < 2 ? '10.0.' + i + '.1/24' : '1.1.1.1/32'}
                    </div>
                  </div>
                </div>
                <StatusChip variant={i < 2 ? 'success' : 'neutral'} dot>
                  {i < 2 ? 'UP' : 'ADMIN'}
                </StatusChip>
              </div>
            ))}
          </div>
        )}

        {activeTab === 'HEALTH' && (
          <div className="flex flex-col items-center justify-center py-12 text-on-surface-variant">
            <Icon name="monitoring" className="text-3xl mb-2 opacity-40" />
            <p className="text-xs font-semibold">Health metrics unavailable</p>
            <p className="text-[10px] mt-1 opacity-60">Trigger a snapshot to collect data</p>
          </div>
        )}
      </div>

      {/* Footer buttons */}
      <div className="px-5 py-4 border-t border-outline/10 flex gap-2">
        <button className="flex-1 flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-lg bg-secondary/10 text-secondary text-xs font-bold hover:bg-secondary/15 transition-colors">
          <Icon name="restart_alt" className="text-base" />
          REBOOT
        </button>
        <button className="flex-1 flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-lg bg-primary text-white text-xs font-bold hover:bg-primary/90 transition-colors">
          <Icon name="edit" className="text-base" />
          EDIT CONFIG
        </button>
      </div>
    </div>
  );
}

export default function Devices() {
  const { data: devices, loading, error, refetch } = useApi(api.devices);
  const [selectedDevice, setSelectedDevice] = useState(null);
  const [activeFilter, setActiveFilter] = useState('ALL');

  const deviceList = Array.isArray(devices) ? devices : [];
  const filteredDevices = filterDevices(deviceList, activeFilter);

  return (
    <div className="flex h-full overflow-hidden">
      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 p-6 overflow-y-auto">
        {/* Filters bar */}
        <div className="flex items-center justify-between mb-5">
          {/* Left: title + count */}
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-extrabold text-on-surface">Inventory</h1>
            <span className="flex items-center justify-center min-w-[28px] h-7 px-2 bg-surface-container-high rounded-full text-xs font-bold text-on-surface-variant">
              {filteredDevices.length}
            </span>
          </div>

          {/* Right: filters + actions */}
          <div className="flex items-center gap-3">
            {/* Toggle buttons */}
            <div className="flex bg-surface-container-low rounded-lg p-1">
              {FILTERS.map((f) => (
                <button
                  key={f}
                  onClick={() => setActiveFilter(f)}
                  className={`px-3.5 py-1.5 rounded-md text-[11px] font-bold transition-all ${
                    activeFilter === f
                      ? 'bg-white shadow-sm text-on-surface'
                      : 'text-on-surface-variant hover:text-on-surface'
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>

            {/* Filter button */}
            <button
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-outline/20 text-xs font-bold text-on-surface-variant hover:bg-surface-container-low transition-colors"
            >
              <Icon name="filter_list" className="text-base" />
              Filter
            </button>

            {/* Add Device button */}
            <button className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-white text-xs font-bold hover:bg-primary/90 transition-colors">
              <Icon name="add" className="text-base" />
              Add Device
            </button>
          </div>
        </div>

        {/* Loading state */}
        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 border-primary/20 border-t-primary rounded-full animate-spin" />
          </div>
        )}

        {/* Error state */}
        {error && (
          <div className="flex items-center gap-3 bg-error/5 border border-error/20 rounded-xl px-5 py-4 mb-4">
            <Icon name="error" className="text-xl text-error" />
            <div>
              <p className="text-sm font-bold text-error">Failed to load devices</p>
              <p className="text-xs text-on-surface-variant mt-0.5">{error.message}</p>
            </div>
            <button
              onClick={refetch}
              className="ml-auto px-3 py-1.5 rounded-lg bg-error/10 text-error text-xs font-bold hover:bg-error/15 transition-colors"
            >
              Retry
            </button>
          </div>
        )}

        {/* Table */}
        {!loading && !error && (
          <DeviceTable
            devices={filteredDevices}
            selectedDevice={selectedDevice}
            onSelect={setSelectedDevice}
          />
        )}
      </div>

      {/* Right detail panel */}
      {selectedDevice && (
        <DetailPanel device={selectedDevice} onClose={() => setSelectedDevice(null)} />
      )}
    </div>
  );
}
