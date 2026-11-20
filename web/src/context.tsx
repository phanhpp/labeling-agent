// Who the page is acting as, and the live policy's section titles, shared by every page.

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setToken } from "./api";
import { savedUser, saveUser, type User } from "./roles";

type Shared = { user: User; setUser: (u: User) => void; sections: Record<string, string>; live: string | null };
const Context = createContext<Shared | null>(null);

export function SharedProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<User>(() => {
    const u = savedUser();
    setToken(u.token);
    return u;
  });
  const [sections, setSections] = useState<Record<string, string>>({});
  const [live, setLive] = useState<string | null>(null);

  const setUser = (u: User) => {
    setToken(u.token);
    saveUser(u);
    setUserState(u);
  };

  useEffect(() => {
    api
      .versions()
      .then((versions) => {
        const name = versions.find((v) => v.status === "live")?.name ?? null;
        setLive(name);
        return name ? api.version(name) : null;
      })
      .then((policy) => {
        if (policy) setSections(Object.fromEntries(policy.body.sections.map((s: any) => [s.code, s.title])));
      })
      .catch(() => {}); // the pages show their own errors
  }, [user]);

  return <Context.Provider value={{ user, setUser, sections, live }}>{children}</Context.Provider>;
}

export function useShared(): Shared {
  const value = useContext(Context);
  if (!value) throw new Error("useShared outside SharedProvider");
  return value;
}
