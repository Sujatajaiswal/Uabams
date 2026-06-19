import type { Severity } from '../types'

const STYLES: Record<Severity, string> = {
  Critical: 'bg-status-critical/10 text-status-critical border-status-critical/30',
  Warning: 'bg-status-warning/10 text-status-warning border-status-warning/30',
  Info: 'bg-status-info/10 text-status-info border-status-info/30',
}

export default function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11.5px] font-semibold uppercase tracking-wide border ${STYLES[severity]}`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {severity}
    </span>
  )
}
