import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import DashboardPage from './pages/DashboardPage'
import GatewayUploadPage from './pages/GatewayUploadPage'
import ThresholdSettingsPage from './pages/ThresholdSettingsPage'
import CalibrationPage from './pages/CalibrationPage'
import AlertsPage from './pages/AlertsPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/gateway-upload" element={<GatewayUploadPage />} />
          <Route path="/threshold-settings" element={<ThresholdSettingsPage />} />
          <Route path="/calibration" element={<CalibrationPage />} />
          <Route path="/alerts" element={<AlertsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
