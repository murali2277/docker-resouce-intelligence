import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { PollingProvider } from './hooks/PollingContext';
import { Sidebar } from './components/Sidebar';
import Overview from './pages/Overview';
import Alerts from './pages/Alerts';
import Recommendations from './pages/Recommendations';
import Forecast from './pages/Forecast';
import ActionsHistory from './pages/ActionsHistory';
import Policies from './pages/Policies';

export default function App() {
  return (
    <PollingProvider>
      <BrowserRouter>
        <div className="app-shell">
          <Sidebar />
          <main className="main-content">
            <Routes>
              <Route path="/"                index element={<Overview />} />
              <Route path="/alerts"          element={<Alerts />} />
              <Route path="/recommendations" element={<Recommendations />} />
              <Route path="/forecast"        element={<Forecast />} />
              <Route path="/actions"         element={<ActionsHistory />} />
              <Route path="/policies"        element={<Policies />} />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
    </PollingProvider>
  );
}
