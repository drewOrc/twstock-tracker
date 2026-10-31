import { Navigate, Route, Routes } from "react-router-dom";
import { ToastProvider } from "./components/Toast";
import { CardProvider } from "./components/CardDrawer";
import { AuthProvider } from "./components/Auth";
import Shell from "./components/Shell";
import { AccountView, AdminView, Home, MarketView, MeView, NotFound, StockPage, StructureView } from "./pages/views";

/* Old paths keep working: each one lands on the section that replaced it (canvas board 27 §1). */
const LEGACY_REDIRECTS: [string, string][] = [
  ["/watchlist", "/me#lists"],
  ["/board", "/me#cards"],
  ["/morning", "/me#today"],
  ["/alerts", "/me#alerts"],
  ["/proposals", "/me#proposals"],
  ["/screener", "/market#screener"],
  ["/graph", "/structure#chain"],
  ["/knowledge", "/structure#knowledge"],
  ["/jobs", "/admin#system"],
  ["/users", "/account"],
];

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
      <CardProvider>
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<Home />} />
            <Route path="/market" element={<MarketView />} />
            <Route path="/me" element={<MeView />} />
            <Route path="/structure" element={<StructureView />} />
            <Route path="/stock/:code" element={<StockPage />} />
            <Route path="/account" element={<AccountView />} />
            <Route path="/admin" element={<AdminView />} />
            {LEGACY_REDIRECTS.map(([from, to]) => (
              <Route key={from} path={from} element={<Navigate to={to} replace />} />
            ))}
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </CardProvider>
      </AuthProvider>
    </ToastProvider>
  );
}
