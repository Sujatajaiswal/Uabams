import axios from 'axios'
import type {
  AlertRecord,
  ArchiveUploadResult,
  CalibrationInput,
  CalibrationRecord,
  DashboardData,
  GatewayStatus,
  ThresholdInput,
  ThresholdSetting,
} from '../types'

// In production this is injected at build time (Render static site env var).
// Falls back to localhost for local `npm run dev` against the docker-compose backend.
const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const API_KEY = import.meta.env.VITE_API_KEY

export const api = axios.create({
  baseURL: BASE_URL,
  timeout: 15000,
})

if (API_KEY) {
  api.defaults.headers.common['X-API-Key'] = API_KEY
}

export async function getDashboard(): Promise<DashboardData> {
  const { data } = await api.get<DashboardData>('/api/v1/dashboard')
  return data
}

export async function getGateways(): Promise<GatewayStatus[]> {
  const { data } = await api.get<GatewayStatus[]>('/api/v1/gateways')
  return data
}

export async function getAlerts(params?: { severity?: string; route?: string }): Promise<AlertRecord[]> {
  const { data } = await api.get<AlertRecord[]>('/api/v1/alerts', { params })
  return data
}

export async function getThresholds(): Promise<ThresholdSetting[]> {
  const { data } = await api.get<ThresholdSetting[]>('/api/v1/threshold')
  return data
}

export async function saveThreshold(payload: ThresholdInput): Promise<ThresholdSetting> {
  const { data } = await api.post<ThresholdSetting>('/api/v1/threshold', payload)
  return data
}

export async function getCalibrationHistory(params?: {
  gatewayId?: string
  axleId?: string
}): Promise<CalibrationRecord[]> {
  const { data } = await api.get<CalibrationRecord[]>('/api/v1/calibration', { params })
  return data
}

export async function saveCalibration(payload: CalibrationInput): Promise<CalibrationRecord> {
  const { data } = await api.post<CalibrationRecord>('/api/v1/calibration', payload)
  return data
}

export interface SimulatedUploadPayload {
  gatewayId: string
  trainId: string
  speed: number
  peak: number
  gps: { lat: number; lon: number }
}

export async function uploadArchive(payload: SimulatedUploadPayload): Promise<ArchiveUploadResult> {
  const { data } = await api.post<ArchiveUploadResult>('/api/v1/archive', payload)
  return data
}

/**
 * Triggers a browser download of the CRIS TMS export bundle (clause 2.5 of
 * the RDSO UABAMS spec: spatial acceleration data + processed peak data,
 * packaged alongside a genuine target .mdb container). See
 * backend/app/services/tms_export.py for the full rationale.
 */
export async function downloadTmsExport(days = 30): Promise<void> {
  const response = await api.get('/api/v1/export/tms', {
    params: { days },
    responseType: 'blob',
  })
  const url = window.URL.createObjectURL(new Blob([response.data]))
  const link = document.createElement('a')
  link.href = url
  link.setAttribute('download', `uabams_tms_export_${days}d.zip`)
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}
