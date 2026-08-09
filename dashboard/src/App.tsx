import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Sidebar } from './components/Sidebar';
import Overview from './pages/Overview';
import Alerts from './pages/Alerts';
import Recommendations from './pages/Recommendations';
import Forecast from './pages/Forecast';

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <Sidebar />
        <main className="main-content">
          <Routes>
            <Route path="/"                index element={<Overview />} />
            <Route path="/alerts"          element={<Alerts />} />
            <Route path="/recommendations" element={<Recommendations />} />
            <Route path="/forecast"        element={<Forecast />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
