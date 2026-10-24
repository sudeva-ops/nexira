import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./client";

export interface RoleGrant {
  code: string;
  mission_id: string | null;
  mission_code: string | null;
}

export interface Me {
  id: string;
  display_name: string;
  email: string;
  roles: RoleGrant[];
}

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => apiGet<Me>("/api/me"), staleTime: 60_000 });
}

/** For hiding actions only; the backend enforces every check (PLT-02). */
export function hasRole(me: Me | undefined, code: string): boolean {
  return me?.roles.some((r) => r.code === code) ?? false;
}

export function roleLabel(role: RoleGrant): string {
  return role.mission_code ? `${role.code} · ${role.mission_code}` : role.code;
}
