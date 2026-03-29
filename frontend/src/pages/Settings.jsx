import { useApi } from '../hooks/useApi';
import { api } from '../api/client';
import Icon from '../components/Icon';
import StatusChip from '../components/StatusChip';

function DepStatus({ name, status }) {
  const ok = status === 'healthy' || status === 'connected' || status === true;
  return (
    <div className="flex items-center justify-between py-4">
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${ok ? 'bg-secondary/10' : 'bg-error/10'}`}>
          <Icon name={ok ? 'check_circle' : 'error'} className={ok ? 'text-secondary' : 'text-error'} />
        </div>
        <div>
          <p className="font-bold text-on-surface">{name}</p>
          <p className="text-[11px] text-on-surface-variant">{typeof status === 'string' ? status : ok ? 'Connected' : 'Unreachable'}</p>
        </div>
      </div>
      <StatusChip variant={ok ? 'success' : 'error'} dot>{ok ? 'HEALTHY' : 'DOWN'}</StatusChip>
    </div>
  );
}

export default function Settings() {
  const { data: health, loading } = useApi(api.healthDeps);

  return (
    <div className="max-w-4xl">
      <div className="mb-10">
        <div className="flex items-center gap-2 mb-2">
          <span className="w-2 h-2 rounded-full bg-primary" />
          <span className="text-[10px] font-bold tracking-widest text-on-surface-variant uppercase">Configuration</span>
        </div>
        <h1 className="text-4xl font-extrabold text-on-surface tracking-tight">Settings</h1>
      </div>

      {/* Service Health */}
      <section className="mb-8">
        <h2 className="text-xl font-bold text-on-surface mb-4">Service Dependencies</h2>
        <div className="bg-surface-container-lowest rounded-xl p-6 shadow-sm">
          {loading ? (
            <p className="text-on-surface-variant py-8 text-center">Checking dependencies...</p>
          ) : health ? (
            <div className="divide-y divide-surface-container-low">
              {Object.entries(health).map(([key, val]) => (
                <DepStatus key={key} name={key} status={typeof val === 'object' ? val.status : val} />
              ))}
            </div>
          ) : (
            <p className="text-on-surface-variant py-8 text-center">Unable to reach backend API</p>
          )}
        </div>
      </section>

      {/* Configuration Sections */}
      <section className="mb-8">
        <h2 className="text-xl font-bold text-on-surface mb-4">Snapshot Schedule</h2>
        <div className="bg-surface-container-lowest rounded-xl p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-bold text-on-surface">Automated Snapshots</p>
              <p className="text-sm text-on-surface-variant">Currently runs every 6 hours (0 */6 * * *)</p>
            </div>
            <button className="px-4 py-2 bg-surface-container-highest text-on-surface rounded-lg text-sm font-medium hover:bg-surface-container-high transition-colors">
              Configure
            </button>
          </div>
        </div>
      </section>

      <section className="mb-8">
        <h2 className="text-xl font-bold text-on-surface mb-4">Integrations</h2>
        <div className="bg-surface-container-lowest rounded-xl shadow-sm divide-y divide-surface-container-low">
          {[
            { name: 'Grafana', desc: 'Device inventory source', icon: 'monitoring' },
            { name: 'Slack', desc: 'Approval notifications', icon: 'chat' },
            { name: 'Jira', desc: 'Ticket management (KSR project)', icon: 'confirmation_number' },
            { name: 'Ollama', desc: 'Local inference (Tier 0)', icon: 'smart_toy' },
          ].map((item) => (
            <div key={item.name} className="flex items-center justify-between p-6">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                  <Icon name={item.icon} className="text-primary" />
                </div>
                <div>
                  <p className="font-bold text-on-surface">{item.name}</p>
                  <p className="text-[11px] text-on-surface-variant">{item.desc}</p>
                </div>
              </div>
              <button className="text-xs font-bold text-primary uppercase tracking-wider hover:underline">
                Configure
              </button>
            </div>
          ))}
        </div>
      </section>

      <section className="mb-8">
        <h2 className="text-xl font-bold text-on-surface mb-4">AI Model Tiers</h2>
        <div className="bg-surface-container-lowest rounded-xl shadow-sm divide-y divide-surface-container-low">
          {[
            { tier: 'Tier 0', model: 'Ollama (qwen2.5:14b)', use: 'Data normalisation', cost: 'Free' },
            { tier: 'Tier 1', model: 'Claude Haiku', use: 'Topology analysis', cost: 'Low' },
            { tier: 'Tier 2', model: 'Claude Sonnet', use: 'Remediation reasoning', cost: 'Medium' },
            { tier: 'Tier 3', model: 'Claude Opus', use: 'Complex escalation', cost: 'High' },
          ].map((item) => (
            <div key={item.tier} className="flex items-center justify-between p-6">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] font-bold bg-primary/10 text-primary px-2 py-0.5 rounded">{item.tier}</span>
                  <p className="font-bold text-on-surface">{item.model}</p>
                </div>
                <p className="text-[11px] text-on-surface-variant">{item.use} — {item.cost} cost</p>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
