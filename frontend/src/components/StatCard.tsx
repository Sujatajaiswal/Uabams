import type { LucideIcon } from 'lucide-react'

interface Props {
  label: string
  value: string | number
  icon: LucideIcon
  sublabel?: string
  tone?: 'default' | 'ok' | 'warning' | 'critical'
}

const TONE_BORDER: Record<string, string> = {
  default: 'border-l-rail-blue',
  ok: 'border-l-status-ok',
  warning: 'border-l-status-warning',
  critical: 'border-l-status-critical',
}

export default function StatCard({ label, value, icon: Icon, sublabel, tone = 'default' }: Props) {
  return (
    <div className={`panel border-l-[3px] ${TONE_BORDER[tone]} p-4 flex items-start justify-between`}>
      <div>
        <p className="label-eyebrow">{label}</p>
        <p className="font-mono font-semibold text-[28px] leading-tight text-rail-navy mt-1">
          {value}
        </p>
        {sublabel && <p className="text-[12px] text-rail-steelLight mt-0.5">{sublabel}</p>}
      </div>
      <div className="w-9 h-9 rounded-md bg-rail-fog flex items-center justify-center text-rail-blue shrink-0">
        <Icon size={18} strokeWidth={2} />
      </div>
    </div>
  )
}
