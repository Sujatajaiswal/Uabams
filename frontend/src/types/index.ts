export interface DashboardCards {
  activeTrains: number
  uploadedSessions: number
  alertsGenerated: number
  gatewaysOnline: number
  gatewaysTotal: number
  lastUploadTime: string | null
}

export interface RmsPoint {
  timestamp: string
  rms: number
  axleId: string
}

export interface PeakPoint {
  timestamp: string
  peak: number
  axleId: string
}

export interface RouteHeatmapPoint {
  route: string
  violations: number
  avgPeak: number
  sessions: number
}

export interface ThresholdViolationPoint {
  date: string
  critical: number
  warning: number
  info: number
}

export interface GpsLocationPoint {
  trainId: string
  gatewayId: string
  lat: number
  lon: number
  speedKmph: number
  status: 'Normal' | 'Alert'
  timestamp: string
}

export interface SessionRow {
  trainId: string
  gatewayId: string
  route: string
  speedKmph: number
  peak: number
  status: 'Normal' | 'Alert'
  timestamp: string
}

export interface DashboardData {
  cards: DashboardCards
  rmsTrend: RmsPoint[]
  peakTrend: PeakPoint[]
  routeHeatmap: RouteHeatmapPoint[]
  thresholdViolations: ThresholdViolationPoint[]
  gpsLocations: GpsLocationPoint[]
  sessionsTable: SessionRow[]
}

export interface GatewayStatus {
  gatewayId: string
  status: 'online' | 'offline'
  lastSeenAt: string | null
  lastUploadAt: string | null
}

export interface ThresholdSetting {
  id: number
  route: string
  verticalThreshold: number
  lateralThreshold: number
  alertsEnabled: boolean
  updatedAt: string
}

export interface ThresholdInput {
  route: string
  verticalThreshold: number
  lateralThreshold: number
  alertsEnabled: boolean
}

export interface CalibrationRecord {
  id: number
  gatewayId: string
  axleId: string
  wheelDiameterMm: number
  wearPercent: number
  correctionFactor: number
  createdAt: string
}

export interface CalibrationInput {
  gatewayId: string
  axleId: string
  wheelDiameterMm: number
  wearPercent: number
  correctionFactor: number
}

export type Severity = 'Critical' | 'Warning' | 'Info'

export interface AlertRecord {
  id: number
  time: string
  gatewayId: string
  trainId: string
  route: string
  axleId: string | null
  metric: 'vertical' | 'lateral'
  peak: number
  threshold: number
  speedKmph: number
  severity: Severity
  message: string
  nearestTrackFeatureKm: number | null
}

export interface ArchiveUploadResult {
  status: string
  archiveId: number
  alertsGenerated: number
  message?: string
}
