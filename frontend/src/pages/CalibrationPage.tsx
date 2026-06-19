import { useEffect, useState } from 'react'
import { Save } from 'lucide-react'
import Topbar from '../components/Topbar'
import { getCalibrationHistory, saveCalibration } from '../api/client'
import type { CalibrationRecord } from '../types'

export default function CalibrationPage() {
  const [history, setHistory] = useState<CalibrationRecord[]>([])
  const [gatewayId, setGatewayId] = useState('GW001')
  const [axleId, setAxleId] = useState('AX01')
  const [wheelDiameterMm, setWheelDiameterMm] = useState(920)
  const [wearPercent, setWearPercent] = useState(4)
  const [correctionFactor, setCorrectionFactor] = useState(1.02)
  const [saving, setSaving] = useState(false)
  const [savedMsg, setSavedMsg] = useState<string | null>(null)

  function refresh() {
    getCalibrationHistory().then(setHistory).catch(() => {})
  }

  useEffect(() => {
    refresh()
  }, [])

  async function handleSave() {
    setSaving(true)
    setSavedMsg(null)
    try {
      await saveCalibration({ gatewayId, axleId, wheelDiameterMm, wearPercent, correctionFactor })
      setSavedMsg(`Calibration recorded for ${gatewayId} / ${axleId}.`)
      refresh()
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <Topbar title="Calibration" subtitle="Module 4 - wheel wear compensation per axle" />

      <div className="p-6 space-y-6">
        <div className="panel p-5 max-w-2xl">
          <p className="font-display font-medium text-[14px] text-rail-navy mb-1">Record Calibration</p>
          <p className="text-[13px] text-rail-steelLight mb-5">
            distance = encoderPulse &times; correctionFactor. Every save appends a new history row -
            nothing is overwritten, so the full wear timeline per axle is retained.
          </p>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label-eyebrow block mb-1.5">Gateway ID</label>
              <input
                value={gatewayId}
                onChange={(e) => setGatewayId(e.target.value)}
                className="w-full border border-rail-line rounded-md px-3 py-2 text-[13.5px] font-mono focus:outline-none focus:ring-2 focus:ring-rail-blue/30 focus:border-rail-blue"
              />
            </div>
            <div>
              <label className="label-eyebrow block mb-1.5">Axle ID</label>
              <input
                value={axleId}
                onChange={(e) => setAxleId(e.target.value)}
                className="w-full border border-rail-line rounded-md px-3 py-2 text-[13.5px] font-mono focus:outline-none focus:ring-2 focus:ring-rail-blue/30 focus:border-rail-blue"
              />
            </div>
            <div>
              <label className="label-eyebrow block mb-1.5">Wheel Diameter (mm)</label>
              <input
                type="number"
                value={wheelDiameterMm}
                onChange={(e) => setWheelDiameterMm(Number(e.target.value))}
                className="w-full border border-rail-line rounded-md px-3 py-2 text-[13.5px] font-mono focus:outline-none focus:ring-2 focus:ring-rail-blue/30 focus:border-rail-blue"
              />
            </div>
            <div>
              <label className="label-eyebrow block mb-1.5">Wheel Wear (%)</label>
              <input
                type="number"
                min={0}
                max={100}
                value={wearPercent}
                onChange={(e) => setWearPercent(Number(e.target.value))}
                className="w-full border border-rail-line rounded-md px-3 py-2 text-[13.5px] font-mono focus:outline-none focus:ring-2 focus:ring-rail-blue/30 focus:border-rail-blue"
              />
            </div>
            <div className="col-span-2">
              <label className="label-eyebrow block mb-1.5">Correction Factor</label>
              <input
                type="number"
                step={0.01}
                value={correctionFactor}
                onChange={(e) => setCorrectionFactor(Number(e.target.value))}
                className="w-full border border-rail-line rounded-md px-3 py-2 text-[13.5px] font-mono focus:outline-none focus:ring-2 focus:ring-rail-blue/30 focus:border-rail-blue"
              />
            </div>
          </div>

          <div className="flex items-center gap-3 pt-5">
            <button
              onClick={handleSave}
              disabled={saving}
              className="inline-flex items-center gap-2 bg-rail-blue hover:bg-rail-blueLight text-white text-[13px] font-medium rounded-md px-4 py-2.5 transition-colors disabled:opacity-60"
            >
              <Save size={15} />
              {saving ? 'Saving...' : 'Save Calibration'}
            </button>
            {savedMsg && <span className="text-[12.5px] text-status-ok">{savedMsg}</span>}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <p className="font-display font-medium text-[14px] text-rail-navy">Calibration History</p>
            <span className="label-eyebrow">{history.length} record(s)</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left text-rail-steelLight border-b border-rail-line">
                  <th className="px-4 py-2.5 font-medium">Gateway</th>
                  <th className="px-4 py-2.5 font-medium">Axle</th>
                  <th className="px-4 py-2.5 font-medium">Wheel Dia. (mm)</th>
                  <th className="px-4 py-2.5 font-medium">Wear (%)</th>
                  <th className="px-4 py-2.5 font-medium">Correction Factor</th>
                  <th className="px-4 py-2.5 font-medium">Recorded</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id} className="border-b border-rail-line last:border-0 hover:bg-rail-fog/60">
                    <td className="px-4 py-2.5 font-mono text-rail-navy">{h.gatewayId}</td>
                    <td className="px-4 py-2.5 font-mono text-rail-steel">{h.axleId}</td>
                    <td className="px-4 py-2.5 font-mono text-rail-steel">{h.wheelDiameterMm}</td>
                    <td className="px-4 py-2.5 font-mono text-rail-steel">{h.wearPercent}</td>
                    <td className="px-4 py-2.5 font-mono text-rail-steel">{h.correctionFactor}</td>
                    <td className="px-4 py-2.5 text-rail-steelLight font-mono text-[12px]">
                      {new Date(h.createdAt).toLocaleString('en-IN')}
                    </td>
                  </tr>
                ))}
                {history.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-rail-steelLight">
                      No calibration records yet.
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
