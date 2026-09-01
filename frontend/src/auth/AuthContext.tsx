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
  // Role groups the current user is a read-only observer admin of (empty
  // array for a normal user). Derived from /api/me.
  managedGroupIds: number[];
  managedGroupNames: string[];
  // True when the caller administers at least one role group and is NOT
  // staff — i.e. this is a *pure* role-group admin who needs the scoped
  // views on Users / Statistics / Logs and the "you administer …" hint bar.
  // Staff who also happen to hold adminships are handled by the platform-role
  // path (they see everything anyway).
  isRoleGroupAdmin: boolean;
  login: () => void;
  tokenLogin: (token: string) => Promise<void>;
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

  async function tokenLogin(token: string) {
    const session = await api.post<SessionOut>("/api/auth/token-login", { token });
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
  const managedGroupIds = user?.managed_group_ids ?? [];
  const managedGroupNames = user?.managed_group_names ?? [];
  const isRoleGroupAdmin = managedGroupIds.length > 0 && !isStaff;

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        isStaff,
        isOwner,
        managedGroupIds,
        managedGroupNames,
        isRoleGroupAdmin,
        login,
        tokenLogin,
        devLogin,
        logout,
        reload,
      }}
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
