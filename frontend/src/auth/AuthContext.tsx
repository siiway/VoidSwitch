import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, API_BASE, clearToken, getToken, setToken } from "../api/client";
import { armAnnouncementsPopup } from "../components/Announcements";
import type { User } from "../api/types";
import { isStaff as checkStaff, isOwner as checkOwner } from "./constants";

interface SessionOut {
  access_token: string;
  expires_in: number;
  user: User;
}

interface AuthState {
  user: User | null;
  loading: boolean;
  isStaff: boolean;
  isOwner: boolean;
  login: () => void;
  devLogin: () => Promise<void>;
  logout: () => void;
  reload: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  async function reload() {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await api.get<User>("/api/me");
      setUser(me);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  function login() {
    location.assign(`${API_BASE}/api/auth/login?redirect=1`);
  }

  async function devLogin() {
    const session = await api.post<SessionOut>("/api/auth/dev-login");
    setToken(session.access_token);
    armAnnouncementsPopup();
    setUser(session.user);
  }

  function logout() {
    clearToken();
    setUser(null);
    location.assign("/login");
  }

  // Derived from the shared role tiers (auth/constants.ts) so these checks can't
  // drift from the backend's OWNER_ROLES / STAFF_ROLES definitions.
  const isOwner = checkOwner(user?.role);
  const isStaff = checkStaff(user?.role);

  return (
    <AuthContext.Provider
      value={{ user, loading, isStaff, isOwner, login, devLogin, logout, reload }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
