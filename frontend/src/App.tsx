import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useAuthStore } from "./stores/auth";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Mailboxes from "./pages/Mailboxes";
import ImportWizard from "./pages/ImportWizard";
import Domains from "./pages/Domains";
import Aliases from "./pages/Aliases";
import Keepalive from "./pages/Keepalive";
import FetchCenter from "./pages/FetchCenter";
import MailCenter from "./pages/MailCenter";
import Tasks from "./pages/Tasks";
import Pools from "./pages/Pools";
import Rules from "./pages/Rules";

function Protected({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <Protected>
              <Layout />
            </Protected>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="mailboxes" element={<Mailboxes />} />
          <Route path="import" element={<ImportWizard />} />
          <Route path="domains" element={<Domains />} />
          <Route path="aliases" element={<Aliases />} />
          <Route path="keepalive" element={<Keepalive />} />
          <Route path="fetch" element={<FetchCenter />} />
          <Route path="mails" element={<MailCenter />} />
          <Route path="tasks" element={<Tasks />} />
          <Route path="pools" element={<Pools />} />
          <Route path="rules" element={<Rules />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
