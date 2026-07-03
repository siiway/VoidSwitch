// Mirrors the backend's OWNER_ROLES / STAFF_ROLES sets (core/auth.py).
// Keeping them here avoids duplicating the role-check logic inline.

export const OWNER_ROLES = new Set(["owner", "co-owner"]);
export const STAFF_ROLES = new Set(["owner", "co-owner", "admin"]);

export function isOwner(role: string | undefined | null): boolean {
  return role != null && OWNER_ROLES.has(role);
}

export function isStaff(role: string | undefined | null): boolean {
  return role != null && STAFF_ROLES.has(role);
}
