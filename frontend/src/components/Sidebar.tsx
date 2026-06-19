import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  UploadCloud,
  SlidersHorizontal,
  Gauge,
  AlertTriangle,
  TrainFront,
} from 'lucide-react'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/gateway-upload', label: 'Gateway Upload', icon: UploadCloud },
  { to: '/threshold-settings', label: 'Threshold Settings', icon: SlidersHorizontal },
  { to: '/calibration', label: 'Calibration', icon: Gauge },
  { to: '/alerts', label: 'Alerts', icon: AlertTriangle },
]

export default function Sidebar() {
  return (
    <aside className="w-60 shrink-0 bg-rail-navy text-white flex flex-col h-screen sticky top-0">
      <div className="flex items-center gap-2.5 px-5 h-16 border-b border-white/10">
        <div className="w-8 h-8 rounded-md bg-rail-blue flex items-center justify-center">
          <TrainFront size={18} strokeWidth={2.25} />
        </div>
        <div className="leading-tight">
          <p className="font-display font-semibold text-[15px] tracking-wide">UABAMS</p>
          <p className="text-[10.5px] text-white/50 -mt-0.5">Indian Railways</p>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              [
                'flex items-center gap-3 px-3 py-2.5 rounded-md text-[13.5px] font-medium transition-colors',
                isActive
                  ? 'bg-rail-blue text-white'
                  : 'text-white/65 hover:text-white hover:bg-white/5',
              ].join(' ')
            }
          >
            <Icon size={17} strokeWidth={2} />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="px-5 py-4 border-t border-white/10 text-[11px] text-white/40 font-mono">
        Cloud Receive &middot; v1.0.0
      </div>
    </aside>
  )
}
