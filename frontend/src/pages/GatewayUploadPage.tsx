import { useState } from 'react'
import { UploadCloud, CheckCircle2, XCircle } from 'lucide-react'
import Topbar from '../components/Topbar'
import { uploadArchive } from '../api/client'
import type { ArchiveUploadResult } from '../types'

interface UploadLogEntry {
  gatewayId: string
  trainId: string
  timestamp: string
  status: 'success' | 'failed'
  detail: string
}

const SAMPLE_GATEWAYS = ['GW001', 'GW002', 'GW003', 'GW004']
const SAMPLE_TRAINS = ['TRAIN07', 'TRAIN12', 'TRAIN21', 'TRAIN34']

function randomBetween(min: number, max: number) {
  return Math.round((Math.random() * (max - min) + min) * 10) / 10
}

export default function GatewayUploadPage() {
  const [log, setLog] = useState<UploadLogEntry[]>([])
  const [uploading, setUploading] = useState(false)

  async function handleSimulateUpload() {
    setUploading(true)
    const gatewayId = SAMPLE_GATEWAYS[Math.floor(Math.random() * SAMPLE_GATEWAYS.length)]
    const trainId = SAMPLE_TRAINS[Math.floor(Math.random() * SAMPLE_TRAINS.length)]
    const timestamp = new Date().toISOString()

    const payload = {
      gatewayId,
      trainId,
      speed: randomBetween(60, 130),
      peak: randomBetween(15, 95),
      gps: { lat: 12.97 + Math.random() * 0.3, lon: 77.59 + Math.random() * 2 },
    }

    try {
      const result: ArchiveUploadResult = await uploadArchive(payload)
      setLog((prev) => [
        {
          gatewayId,
          trainId,
          timestamp,
          status: 'success',
          detail: `archiveId ${result.archiveId} - ${result.alertsGenerated} alert(s) generated`,
        },
        ...prev,
      ])
    } catch (err: any) {
      setLog((prev) => [
        {
          gatewayId,
          trainId,
          timestamp,
          status: 'failed',
          detail: err?.response?.data?.detail
            ? JSON.stringify(err.response.data.detail)
            : 'Upload failed - check backend connectivity',
        },
        ...prev,
      ])
    } finally {
      setUploading(false)
    }
  }

  return (
    <>
      <Topbar title="Gateway Upload" subtitle="Module 2 - simulate an edge gateway session archive upload" />

      <div className="p-6 space-y-6">
        <div className="panel p-5">
          <p className="font-display font-medium text-[14px] text-rail-navy mb-1">
            Simulate Session Upload
          </p>
          <p className="text-[13px] text-rail-steelLight mb-4 max-w-2xl">
            Sends a PUT/POST <code className="font-mono bg-rail-fog px-1 py-0.5 rounded">/api/v1/archive</code>{' '}
            request with a randomly generated gateway/train/speed/peak/GPS payload, the same shape a real
            UABAMS gateway sends after capturing a measurement session. For a continuous live feed instead
            of one-off clicks, run <code className="font-mono bg-rail-fog px-1 py-0.5 rounded">backend/scripts/gateway_simulator.py</code>.
          </p>
          <button
            onClick={handleSimulateUpload}
            disabled={uploading}
            className="inline-flex items-center gap-2 bg-rail-blue hover:bg-rail-blueLight text-white text-[13px] font-medium rounded-md px-4 py-2.5 transition-colors disabled:opacity-60"
          >
            <UploadCloud size={16} />
            {uploading ? 'Uploading...' : 'Upload Session'}
          </button>
        </div>

        <div className="panel">
          <div className="panel-header">
            <p className="font-display font-medium text-[14px] text-rail-navy">Upload Log</p>
            <span className="label-eyebrow">this session</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left text-rail-steelLight border-b border-rail-line">
                  <th className="px-4 py-2.5 font-medium">Gateway ID</th>
                  <th className="px-4 py-2.5 font-medium">Train ID</th>
                  <th className="px-4 py-2.5 font-medium">Timestamp</th>
                  <th className="px-4 py-2.5 font-medium">Upload Status</th>
                </tr>
              </thead>
              <tbody>
                {log.map((entry, i) => (
                  <tr key={i} className="border-b border-rail-line last:border-0 hover:bg-rail-fog/60">
                    <td className="px-4 py-2.5 font-mono text-rail-navy">{entry.gatewayId}</td>
                    <td className="px-4 py-2.5 font-mono text-rail-steel">{entry.trainId}</td>
                    <td className="px-4 py-2.5 text-rail-steelLight font-mono text-[12px]">
                      {new Date(entry.timestamp).toLocaleString('en-IN')}
                    </td>
                    <td className="px-4 py-2.5">
                      <span
                        className={[
                          'inline-flex items-center gap-1.5 text-[12.5px] font-medium',
                          entry.status === 'success' ? 'text-status-ok' : 'text-status-critical',
                        ].join(' ')}
                      >
                        {entry.status === 'success' ? (
                          <CheckCircle2 size={14} />
                        ) : (
                          <XCircle size={14} />
                        )}
                        {entry.detail}
                      </span>
                    </td>
                  </tr>
                ))}
                {log.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-rail-steelLight">
                      No uploads yet - click "Upload Session" above.
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
