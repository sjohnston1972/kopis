import { NavLink } from 'react-router-dom';
import Icon from './Icon';

const navItems = [
  { to: '/', icon: 'dashboard', label: 'Overview' },
  { to: '/topology', icon: 'hub', label: 'Topology' },
  { to: '/devices', icon: 'router', label: 'Devices' },
  { to: '/snapshots', icon: 'camera', label: 'Snapshots' },
  { to: '/approvals', icon: 'verified_user', label: 'Approvals' },
  { to: '/insights', icon: 'psychology', label: 'AI Insights' },
  { to: '/executions', icon: 'terminal', label: 'Executions' },
];

const bottomItems = [
  { to: '/settings', icon: 'settings', label: 'Settings' },
];

function SideLink({ to, icon, label }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `flex items-center gap-3 px-4 py-3 rounded-lg transition-all duration-200 text-sm font-semibold ${
          isActive
            ? 'text-blue-700 bg-blue-50/50'
            : 'text-slate-600 hover:bg-slate-200/50'
        }`
      }
    >
      <Icon name={icon} />
      <span>{label}</span>
    </NavLink>
  );
}

export default function Sidebar() {
  return (
    <aside className="fixed left-0 top-0 h-full flex flex-col pt-20 pb-6 px-4 w-64 bg-slate-50 z-30">
      <div className="mb-8 px-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-primary flex items-center justify-center text-white shadow-lg shadow-primary/20">
            <Icon name="hub" />
          </div>
          <div>
            <h2 className="text-sm font-bold tracking-tight text-slate-900">Kopis Network</h2>
            <p className="text-[10px] uppercase tracking-widest text-secondary font-bold">Operational</p>
          </div>
        </div>
      </div>

      <nav className="flex-1 flex flex-col gap-1">
        {navItems.map((item) => (
          <SideLink key={item.to} {...item} />
        ))}
      </nav>

      <div className="mt-auto border-t border-slate-200 pt-6 flex flex-col gap-1">
        {bottomItems.map((item) => (
          <SideLink key={item.to} {...item} />
        ))}
      </div>
    </aside>
  );
}
