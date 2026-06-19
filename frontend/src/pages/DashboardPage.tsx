import { useEffect, useState } from 'react'
import {
  TrainFront, UploadCloud, AlertTriangle, Radio, Clock3, Download,
} from 'lucide-react'
import {
  LineChart, Line, BarChart, Bar, ScatterChart, Scatter, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend, ZAxis,
} from 'recharts'
import Topbar from '../components/Topbar'
import StatCard from '../components/StatCard'
import StatusPill from '../components/StatusPill'
import { getDashboard, downloadTmsExport } from '../api/client'
import type { DashboardData } from '../types'

const AXIS_STYLE = { fontSize: 11, fill: '#7B879A' }

function fmtTime(iso: string) {
  return new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const load = () => {
      getDashboard()
        .then((d) => {
          setData(d)
          setError(null)
        })
        .catch(() => setError('Could not reach the UABAMS cloud API. Is the backend running?'))
        .finally(() => setLoading(false))
    }
    load()
    const poll = setInterval(load, 20000)
    return () => clearInterval(poll)
  }, [])

  async function handleExport() {
    setExporting(true)
    try {
      await downloadTmsExport(30)
    } finally {
      setExporting(false)
    }
  }

  return (
    <>
      <Topbar title="Dashboard Overview" subtitle="Fleet-wide axle box acceleration monitoring" />

      <div className="p-6 space-y-6">
        {error && (
          <div className="panel p-4 text-[13px] text-status-critical border-status-critical/30 bg-status-critical/5">
            {error}
          </div>
        )}

        {/* Overview cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          <StatCard
            label="Active Trains"
            value={loading ? '--' : data?.cards.activeTrains ?? 0}
            icon={TrainFront}
            sublabel="last 24 hours"
          />
          <StatCard
            label="Uploaded Sessions"
            value={loading ? '--' : data?.cards.uploadedSessions ?? 0}
            icon={UploadCloud}
            sublabel="all-time total"
          />
          <StatCard
            label="Alerts Generated"
            value={loading ? '--' : data?.cards.alertsGenerated ?? 0}
            icon={AlertTriangle}
            tone="warning"
            sublabel="all-time total"
          />
          <StatCard
            label="Gateway Status"
            value={loading ? '--' : `${data?.cards.gatewaysOnline ?? 0}/${data?.cards.gatewaysTotal ?? 0}`}
            icon={Radio}
            tone="ok"
            sublabel="online / total"
          />
          <StatCard
            label="Last Upload Time"
            value={
              loading || !data?.cards.lastUploadTime
                ? '--'
                : fmtTime(data.cards.lastUploadTime)
            }
            icon={Clock3}
            sublabel={
              data?.cards.lastUploadTime
                ? new Date(data.cards.lastUploadTime).toLocaleDateString('en-IN')
                : undefined
            }
          />
        </div>

        {/* Charts row 1: RMS trend + Peak trend */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="panel">
            <div className="panel-header">
              <p className="font-display font-medium text-[14px] text-rail-navy">RMS Trend</p>
              <span className="label-eyebrow">g, per axle reading</span>
            </div>
            <div className="p-3 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data?.rmsTrend ?? []}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#EEF1F5" />
                  <XAxis dataKey="timestamp" tickFormatter={fmtTime} tick={AXIS_STYLE} />
                  <YAxis tick={AXIS_STYLE} />
                  <Tooltip labelFormatter={(v) => fmtTime(v as string)} />
                  <Line type="monotone" dataKey="rms" stroke="#1B5FAE" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <p className="font-display font-medium text-[14px] text-rail-navy">Peak Acceleration</p>
              <span className="label-eyebrow">g, per axle reading</span>
            </div>
            <div className="p-3 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data?.peakTrend ?? []}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#EEF1F5" />
                  <XAxis dataKey="timestamp" tickFormatter={fmtTime} tick={AXIS_STYLE} />
                  <YAxis tick={AXIS_STYLE} />
                  <Tooltip labelFormatter={(v) => fmtTime(v as string)} />
                  <Line type="monotone" dataKey="peak" stroke="#C5293A" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* Charts row 2: Route heatmap + Threshold violations */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="panel">
            <div className="panel-header">
              <p className="font-display font-medium text-[14px] text-rail-navy">Route Heatmap</p>
              <span className="label-eyebrow">violations by route</span>
            </div>
            <div className="p-3 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data?.routeHeatmap ?? []}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#EEF1F5" />
                  <XAxis dataKey="route" tick={AXIS_STYLE} />
                  <YAxis tick={AXIS_STYLE} />
                  <Tooltip />
                  <Bar dataKey="violations" fill="#C77A12" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <p className="font-display font-medium text-[14px] text-rail-navy">Threshold Violations</p>
              <span className="label-eyebrow">last 14 days, by severity</span>
            </div>
            <div className="p-3 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data?.thresholdViolations ?? []}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#EEF1F5" />
                  <XAxis dataKey="date" tick={AXIS_STYLE} />
                  <YAxis tick={AXIS_STYLE} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="critical" stackId="a" fill="#C5293A" name="Critical" />
                  <Bar dataKey="warning" stackId="a" fill="#C77A12" name="Warning" />
                  <Bar dataKey="info" stackId="a" fill="#2E7BD6" name="Info" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* GPS locations + Sessions table + TMS export */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="panel">
            <div className="panel-header">
              <p className="font-display font-medium text-[14px] text-rail-navy">GPS Locations</p>
              <span className="label-eyebrow">latest position per train</span>
            </div>
            <div className="p-3 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart>
                  <CartesianGrid strokeDasharray="3 3" stroke="#EEF1F5" />
                  <XAxis type="number" dataKey="lon" name="Longitude" tick={AXIS_STYLE} domain={['auto', 'auto']} />
                  <YAxis type="number" dataKey="lat" name="Latitude" tick={AXIS_STYLE} domain={['auto', 'auto']} />
                  <ZAxis type="number" dataKey="speedKmph" range={[40, 200]} name="Speed" />
                  <Tooltip
                    cursor={{ strokeDasharray: '3 3' }}
                    formatter={(value, name) => [value, name]}
                    labelFormatter={() => ''}
                  />
                  <Scatter
                    name="Normal"
                    data={(data?.gpsLocations ?? []).filter((g) => g.status === 'Normal')}
                    fill="#1B5FAE"
                  />
                  <Scatter
                    name="Alert"
                    data={(data?.gpsLocations ?? []).filter((g) => g.status === 'Alert')}
                    fill="#C5293A"
                  />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
            <p className="px-4 pb-3 text-[11px] text-rail-steelLight">
              Plotted by longitude / latitude. Production deployments can swap this for a tile-based
              map (Leaflet/Google Maps) with an API key.
            </p>
          </div>

          <div className="panel flex flex-col">
            <div className="panel-header">
              <div>
                <p className="font-display font-medium text-[14px] text-rail-navy">CRIS TMS Export</p>
                <p className="text-[11.5px] text-rail-steelLight">
                  Spatial acceleration + processed peak data (RDSO TM/IM/434, clause 2.5)
                </p>
              </div>
            </div>
            <div className="p-4 flex-1 flex flex-col justify-between gap-3">
              <p className="text-[13px] text-rail-steel leading-relaxed">
                Generates the two required hand-off datasets plus a genuine target Access (.mdb)
                container for the CRIS TMS server. See the bundled README for the MDB population
                step (Microsoft's Jet/ACE write engine is Windows-only).
              </p>
              <button
                onClick={handleExport}
                disabled={exporting}
                className="inline-flex items-center justify-center gap-2 bg-rail-navy hover:bg-rail-navyLight text-white text-[13px] font-medium rounded-md px-4 py-2.5 transition-colors disabled:opacity-60"
              >
                <Download size={15} />
                {exporting ? 'Preparing export...' : 'Export to TMS (last 30 days)'}
              </button>
            </div>
          </div>
        </div>

        {/* Sessions table */}
        <div className="panel">
          <div className="panel-header">
            <p className="font-display font-medium text-[14px] text-rail-navy">Recent Sessions</p>
            <span className="label-eyebrow">latest 25</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left text-rail-steelLight border-b border-rail-line">
                  <th className="px-4 py-2.5 font-medium">Train</th>
                  <th className="px-4 py-2.5 font-medium">Route</th>
                  <th className="px-4 py-2.5 font-medium">Speed (km/h)</th>
                  <th className="px-4 py-2.5 font-medium">Peak (g)</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {(data?.sessionsTable ?? []).map((row, i) => (
                  <tr key={i} className="border-b border-rail-line last:border-0 hover:bg-rail-fog/60">
                    <td className="px-4 py-2.5 font-medium text-rail-navy">{row.trainId}</td>
                    <td className="px-4 py-2.5 text-rail-steel">{row.route}</td>
                    <td className="px-4 py-2.5 font-mono text-rail-steel">{row.speedKmph.toFixed(0)}</td>
                    <td className="px-4 py-2.5 font-mono text-rail-steel">{row.peak.toFixed(1)}</td>
                    <td className="px-4 py-2.5"><StatusPill status={row.status} /></td>
                    <td className="px-4 py-2.5 text-rail-steelLight font-mono text-[12px]">
                      {new Date(row.timestamp).toLocaleString('en-IN')}
                    </td>
                  </tr>
                ))}
                {(data?.sessionsTable ?? []).length === 0 && !loading && (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-rail-steelLight">
                      No sessions uploaded yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  )
}
