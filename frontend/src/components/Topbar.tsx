import { useEffect, useState } from 'react'
import { Wifi, WifiOff, Clock } from 'lucide-react'
import type { GatewayStatus } from '../types'
import { getGateways } from '../api/client'

interface Props {
  title: string
  subtitle?: string
}

export default function Topbar({ title, subtitle }: Props) {
  const [gateways, setGateways] = useState<GatewayStatus[]>([])
  const [now, setNow] = useState(new Date())

  useEffect(() => {
    const load = () => getGateways().then(setGateways).catch(() => {})
    load()
    const poll = setInterval(load, 15000)
    const clock = setInterval(() => setNow(new Date()), 1000)
    return () => {
      clearInterval(poll)
      clearInterval(clock)
    }
  }, [])

  return (
    <header className="h-16 bg-white border-b border-rail-line flex items-center justify-between px-6 sticky top-0 z-10">
      <div>
        <h1 className="font-display font-semibold text-lg text-rail-navy tracking-wide">{title}</h1>
        {subtitle && <p className="text-[12.5px] text-rail-steelLight -mt-0.5">{subtitle}</p>}
      </div>

      <div className="flex items-center gap-6">
        {/* Live status rail - signature SCADA-style indicator strip */}
        <div className="flex items-center gap-2 bg-rail-fog rounded-md px-3 py-1.5 border border-rail-line">
          <span className="label-eyebrow">Gateways</span>
          <div className="flex items-center gap-1">
            {gateways.length === 0 && (
              <span className="text-[11px] text-rail-steelLight font-mono">--</span>
            )}
            {gateways.map((gw) => (
              <span
                key={gw.gatewayId}
                title={`${gw.gatewayId}: ${gw.status}`}
                className={[
                  'w-2.5 h-2.5 rounded-full',
                  gw.status === 'online' ? 'bg-status-ok' : 'bg-status-offline',
                ].join(' ')}
              />
            ))}
          </div>
          {gateways.some((g) => g.status === 'online') ? (
            <Wifi size={14} className="text-status-ok" />
          ) : (
            <WifiOff size={14} className="text-status-offline" />
          )}
        </div>

        <div className="flex items-center gap-1.5 text-rail-steel font-mono text-[13px]">
          <Clock size={14} />
          {now.toLocaleTimeString('en-IN', { hour12: false })}
        </div>
      </div>
    </header>
  )
}
