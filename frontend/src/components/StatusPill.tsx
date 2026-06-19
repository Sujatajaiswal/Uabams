interface Props {
  status: string
}

const TONE: Record<string, string> = {
  online: 'bg-status-ok',
  Normal: 'bg-status-ok',
  success: 'bg-status-ok',
  offline: 'bg-status-offline',
  Alert: 'bg-status-critical',
  failed: 'bg-status-critical',
}

export default function StatusPill({ status }: Props) {
  const dot = TONE[status] ?? 'bg-rail-steelLight'
  return (
    <span className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-rail-steel">
      <span className={`w-2 h-2 rounded-full ${dot}`} />
      {status}
    </span>
  )
}
