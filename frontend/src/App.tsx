import { Navigate, Route, Routes } from "react-router-dom";
import { Spinner } from "@fluentui/react-components";
import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { Login } from "./pages/Login";
import { LoginCallback } from "./pages/LoginCallback";
import { Dashboard } from "./pages/Dashboard";
import { Providers } from "./pages/Providers";
import { ProviderKeys } from "./pages/ProviderKeys";
import { Proxies } from "./pages/Proxies";
import { Tokens } from "./pages/Tokens";
import { Users } from "./pages/Users";
import { SettingsPage } from "./pages/Settings";
import { Logs } from "./pages/Logs";
import { MyToken } from "./pages/MyToken";
import { Chat } from "./pages/Chat";
import type { ReactNode } from "react";

function Protected({
  children,
  staff,
  owner,
}: {
  children: ReactNode;
  staff?: boolean;
  owner?: boolean;
}) {
  const { user, loading, isStaff, isOwner } = useAuth();
  if (loading) {
    return (
      <div style={{ display: "grid", placeItems: "center", height: "100vh" }}>
        <Spinner label="Loading…" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (owner && !isOwner) return <Navigate to="/providers" replace />;
  if (staff && !isStaff) return <Navigate to="/providers" replace />;
  return <>{children}</>;
}

function Home() {
  const { isStaff } = useAuth();
  return <Navigate to={isStaff ? "/dashboard" : "/providers"} replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/login/callback" element={<LoginCallback />} />
      <Route
        element={
          <Protected>
            <Layout />
          </Protected>
        }
      >
        <Route path="/" element={<Home />} />
        <Route
          path="/dashboard"
          element={
            <Protected staff>
              <Dashboard />
            </Protected>
          }
        />
        <Route
          path="/providers"
          element={
            <Protected>
              <Providers />
            </Protected>
          }
        />
        <Route
          path="/providers/:id/keys"
          element={
            <Protected>
              <ProviderKeys />
            </Protected>
          }
        />
        <Route
          path="/proxies"
          element={
            <Protected staff>
              <Proxies />
            </Protected>
          }
        />
        <Route
          path="/tokens"
          element={
            <Protected owner>
              <Tokens />
            </Protected>
          }
        />
        <Route
          path="/users"
          element={
            <Protected staff>
              <Users />
            </Protected>
          }
        />
        <Route
          path="/settings"
          element={
            <Protected staff>
              <SettingsPage />
            </Protected>
          }
        />
        <Route
          path="/logs"
          element={
            <Protected>
              <Logs />
            </Protected>
          }
        />
        <Route path="/token" element={<MyToken />} />
        <Route path="/chat" element={<Chat />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
