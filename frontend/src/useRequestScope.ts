import { useRef } from "react";
export type RequestScope = { key: string; version: number };
// Identity plus generation prevents A→B→A from accepting the first A's late mutation.
export function useRequestScope(key: string) {
  const active = useRef<RequestScope>({ key, version: 0 });
  if (active.current.key !== key)
    active.current = { key, version: active.current.version + 1 };
  return {
    capture: () => ({ ...active.current }),
    isCurrent: (request: RequestScope) =>
      request.key === active.current.key &&
      request.version === active.current.version,
  };
}
