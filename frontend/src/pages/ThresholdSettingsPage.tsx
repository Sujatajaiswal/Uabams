import { useEffect, useState } from 'react'
import { Save } from 'lucide-react'
import Topbar from '../components/Topbar'
import { getThresholds, saveThreshold } from '../api/client'
import type { ThresholdSetting } from '../types'

const ROUTE_OPTIONS = ['Bangalore-Chennai', 'Chennai-Coimbatore', 'Mumbai-Pune']

export default function ThresholdSettingsPage() {
  const [thresholds, setThresholds] = useState<ThresholdSetting[]>([])
  const [route, setRoute] = useState(ROUTE_OPTIONS[0])
  const [vertical, setVertical] = useState(50)
  const [lateral, setLateral] = useState(80)
  const [alertsEnabled, setAlertsEnabled] = useState(true)
  const [saving, setSaving] = useState(false)
  const [savedMsg, setSavedMsg] = useState<string | null>(null)

  function refresh() {
    getThresholds().then(setThresholds).catch(() => {})
  }

  useEffect(() => {
    refresh()
  }, [])

  async function handleSave() {
    setSaving(true)
    setSavedMsg(null)
    try {
      await saveThreshold({
        route,
        verticalThreshold: vertical,
        lateralThreshold: lateral,
        alertsEnabled,
      })
      setSavedMsg(`Saved threshold for ${route}.`)
      refresh()
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <Topbar title="Threshold Settings" subtitle="Module 3 - per-route vertical/lateral acceleration limits" />

      <div className="p-6 space-y-6">
        <div className="panel p-5 max-w-2xl">
          <p className="font-display font-medium text-[14px] text-rail-navy mb-1">Set Route Threshold</p>
          <p className="text-[13px] text-rail-steelLight mb-5">
            Alerts fire when speed &ge; 80 km/h and a recorded peak exceeds the route's threshold.
            Severity scales with how far the reading exceeds the limit (Critical / Warning / Info).
          </p>

          <div className="space-y-5">
            <div>
              <label className="label-eyebrow block mb-1.5">Route</label>
              <select
                value={route}
                onChange={(e) => setRoute(e.target.value)}
                className="w-full border border-rail-line rounded-md px-3 py-2 text-[13.5px] focus:outline-none focus:ring-2 focus:ring-rail-blue/30 focus:border-rail-blue"
              >
                {ROUTE_OPTIONS.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="label-eyebrow">Vertical Threshold</label>
                <span className="font-mono text-[13px] text-rail-navy font-semibold">{vertical}g</span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                value={vertical}
                onChange={(e) => setVertical(Number(e.target.value))}
                className="w-full accent-rail-blue"
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="label-eyebrow">Lateral Threshold</label>
                <span className="font-mono text-[13px] text-rail-navy font-semibold">{lateral}g</span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                value={lateral}
                onChange={(e) => setLateral(Number(e.target.value))}
                className="w-full accent-rail-blue"
              />
            </div>

            <label className="flex items-center gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={alertsEnabled}
                onChange={(e) => setAlertsEnabled(e.target.checked)}
                className="w-4 h-4 accent-rail-blue"
              />
              <span className="text-[13.5px] text-rail-navy font-medium">Enable Alerts</span>
            </label>

            <div className="flex items-center gap-3 pt-1">
              <button
                onClick={handleSave}
                disabled={saving}
                className="inline-flex items-center gap-2 bg-rail-blue hover:bg-rail-blueLight text-white text-[13px] font-medium rounded-md px-4 py-2.5 transition-colors disabled:opacity-60"
              >
                <Save size={15} />
                {saving ? 'Saving...' : 'Save Threshold'}
              </button>
              {savedMsg && <span className="text-[12.5px] text-status-ok">{savedMsg}</span>}
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <p className="font-display font-medium text-[14px] text-rail-navy">Configured Routes</p>
            <span className="label-eyebrow">{thresholds.length} route(s)</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left text-rail-steelLight border-b border-rail-line">
                  <th className="px-4 py-2.5 font-medium">Route</th>
                  <th className="px-4 py-2.5 font-medium">Vertical (g)</th>
                  <th className="px-4 py-2.5 font-medium">Lateral (g)</th>
                  <th className="px-4 py-2.5 font-medium">Alerts</th>
                  <th className="px-4 py-2.5 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody>
                {thresholds.map((t) => (
                  <tr key={t.id} className="border-b border-rail-line last:border-0 hover:bg-rail-fog/60">
                    <td className="px-4 py-2.5 font-medium text-rail-navy">{t.route}</td>
                    <td className="px-4 py-2.5 font-mono text-rail-steel">{t.verticalThreshold}</td>
                    <td className="px-4 py-2.5 font-mono text-rail-steel">{t.lateralThreshold}</td>
                    <td className="px-4 py-2.5 text-rail-steel">{t.alertsEnabled ? 'Enabled' : 'Disabled'}</td>
                    <td className="px-4 py-2.5 text-rail-steelLight font-mono text-[12px]">
                      {new Date(t.updatedAt).toLocaleString('en-IN')}
                    </td>
                  </tr>
                ))}
                {thresholds.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-rail-steelLight">
                      No thresholds configured yet.
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
