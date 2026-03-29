const API_BASE = '/api/v1';

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `API error: ${res.status}`);
  }
  return res.json();
}

export const api = {
  // Health & Dashboard
  health: () => request('/health'),
  healthDeps: () => request('/health/dependencies'),
  dashboardMetrics: () => request('/dashboard/metrics'),

  // Devices
  devices: () => request('/devices'),
  device: (id) => request(`/devices/${id}`),
  deviceSnapshot: (id) => request(`/devices/${id}/snapshot`),
  deviceUnmonitored: (id) => request(`/devices/${id}/unmonitored`),
  setDeviceUnmonitored: (id, interfaces) =>
    request(`/devices/${id}/unmonitored`, {
      method: 'PUT',
      body: JSON.stringify({ interfaces }),
    }),
  refreshDevices: () => request('/devices/refresh', { method: 'POST' }),

  // Snapshots
  snapshots: (params) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request(`/snapshots${qs}`);
  },
  snapshotStatus: () => request('/snapshots/status'),
  snapshot: (id) => request(`/snapshots/${id}`),
  snapshotDiff: (id) => request(`/snapshots/${id}/diff`),
  triggerSnapshot: (deviceId) =>
    request('/snapshots', {
      method: 'POST',
      body: JSON.stringify(deviceId ? { device_id: deviceId } : {}),
    }),

  // Findings
  findings: (params) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request(`/findings${qs}`);
  },
  finding: (id) => request(`/findings/${id}`),
  dismissFinding: (id) => request(`/findings/${id}`, { method: 'DELETE' }),
  escalateFinding: (id) => request(`/findings/${id}/escalate`, { method: 'POST' }),

  // Approvals
  approvals: () => request('/approvals'),
  approve: (id, body = {}) => request(`/approvals/${id}/approve`, { method: 'POST', body: JSON.stringify(body) }),
  deny: (id, body = {}) => request(`/approvals/${id}/deny`, { method: 'POST', body: JSON.stringify(body) }),
  approvalHistory: () => request('/approvals/history'),
  expireApprovals: () => request('/approvals/expire', { method: 'POST' }),

  // Pipeline
  pipelineRun: (body) => request('/pipeline/run', { method: 'POST', body: JSON.stringify(body) }),
  pipelineStatus: () => request('/pipeline/status'),
  pipelineStats: () => request('/pipeline/stats'),

  // Execution
  execute: (approvalId) => request(`/execute/${approvalId}`, { method: 'POST' }),

  // Chat (streaming — returns raw Response for SSE consumption)
  chatStream: (messages, model) =>
    fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages, model }),
    }),

  // Topology
  topology: () => request('/topology'),
  topologyLayout: () => request('/topology/layout'),
  saveTopologyLayout: (data) => request('/topology/layout', { method: 'PUT', body: JSON.stringify(data) }),
};
