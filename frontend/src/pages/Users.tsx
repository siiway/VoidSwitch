import {
  Badge,
  Button,
  Dropdown,
  Option,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  tokens,
} from "@fluentui/react-components";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { Role, User } from "../api/types";
import {
  DataTable,
  ErrorText,
  Loading,
  PageHeader,
  formatDate,
  useAsync,
  useNotify,
} from "../components/ui";

const ROLES: Role[] = ["owner", "admin", "member"];

export function Users() {
  const notify = useNotify();
  const { user: me } = useAuth();
  const users = useAsync<User[]>(() => api.get("/api/admin/users"));
  const isOwner = me?.role === "owner";

  async function setRole(u: User, role: Role) {
    try {
      await api.patch(`/api/admin/users/${u.id}`, { role });
      notify("Role updated", `${u.username ?? u.sub} → ${role}`, "success");
      users.reload();
    } catch (e) {
      notify(
        "Update failed",
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  async function toggle(u: User) {
    try {
      await api.patch(`/api/admin/users/${u.id}`, { enabled: !u.enabled });
      users.reload();
    } catch (e) {
      notify(
        "Update failed",
        e instanceof Error ? e.message : String(e),
        "error",
      );
    }
  }

  return (
    <div>
      <PageHeader
        title="Users"
        subtitle="Prism-authenticated accounts and their roles"
      />
      {users.loading ? (
        <Loading />
      ) : users.error ? (
        <ErrorText error={users.error} />
      ) : (
        <DataTable ariaLabel="Users">
          <TableHeader>
            <TableRow>
              <TableHeaderCell>User</TableHeaderCell>
              <TableHeaderCell>Email</TableHeaderCell>
              <TableHeaderCell>Role</TableHeaderCell>
              <TableHeaderCell>Status</TableHeaderCell>
              <TableHeaderCell>Last login</TableHeaderCell>
              <TableHeaderCell>Actions</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(users.data ?? []).map((u) => (
              <TableRow key={u.id}>
                <TableCell>{u.name || u.username || u.sub}</TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {u.email ?? "—"}
                </TableCell>
                <TableCell>
                  {isOwner ? (
                    <Dropdown
                      value={u.role}
                      selectedOptions={[u.role]}
                      onOptionSelect={(_, d) =>
                        d.optionValue && setRole(u, d.optionValue as Role)
                      }
                      style={{ minWidth: 120 }}
                    >
                      {ROLES.map((r) => (
                        <Option key={r} value={r}>
                          {r}
                        </Option>
                      ))}
                    </Dropdown>
                  ) : (
                    <Badge appearance="tint">{u.role}</Badge>
                  )}
                </TableCell>
                <TableCell>
                  <Badge
                    color={u.enabled ? "success" : "danger"}
                    appearance="filled"
                  >
                    {u.enabled ? "active" : "disabled"}
                  </Badge>
                </TableCell>
                <TableCell style={{ color: tokens.colorNeutralForeground3 }}>
                  {formatDate(u.last_login_at)}
                </TableCell>
                <TableCell>
                  <Button
                    size="small"
                    appearance="subtle"
                    disabled={u.id === me?.id}
                    onClick={() => toggle(u)}
                  >
                    {u.enabled ? "Disable" : "Enable"}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTable>
      )}
    </div>
  );
}
