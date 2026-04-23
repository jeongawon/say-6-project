import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import MonitorPage from "./pages/MonitorPage";
import DashboardPage from "./pages/DashboardPage";
import ArchivePage from "./pages/ArchivePage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<MonitorPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/archive" element={<ArchivePage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
