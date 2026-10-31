import { Navigate, Route, Routes } from "react-router-dom";
import { ToastProvider } from "./components/Toast";
import { CardProvider } from "./components/CardDrawer";
import Layout from "./components/Layout";
import Watchlist from "./pages/Watchlist";
import Market from "./pages/Market";
import Screener from "./pages/Screener";
import Alerts from "./pages/Alerts";
import Jobs from "./pages/Jobs";
import Board from "./pages/crm/Board";
import Graph from "./pages/crm/Graph";
import Morning from "./pages/crm/Morning";
import Proposals from "./pages/crm/Proposals";

export default function App() {
  return (
    <ToastProvider>
      <CardProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/watchlist" replace />} />
            <Route path="/watchlist" element={<Watchlist />} />
            <Route path="/market" element={<Market />} />
            <Route path="/screener" element={<Screener />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/board" element={<Board />} />
            <Route path="/graph" element={<Graph />} />
            <Route path="/morning" element={<Morning />} />
            <Route path="/proposals" element={<Proposals />} />
            <Route path="*" element={<Navigate to="/watchlist" replace />} />
          </Route>
        </Routes>
      </CardProvider>
    </ToastProvider>
  );
}
