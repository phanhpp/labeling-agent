// What every page shares: who you are acting as, which policy version you are viewing, the tags on
// each version (latest, previous, live), and whether the side panel is folded.
//
// Viewing a version changes what the pages show. It never changes which version is live: that only
// happens by publishing, or by making a retired version live again.

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setToken, type Version } from "./api";
import { savedUser, saveUser, type User } from "./roles";

export type Tagged = Version & { tags: ("latest" | "previous" | "live")[] };

type Shared = {
  user: User;
  setUser: (u: User) => void;
  versions: Tagged[];
  live: string | null;
  latest: string | null;
  previous: string | null;
  viewing: string | null; // the version the pages show; null means the live one
  setViewing: (name: string | null) => void;
  sections: Record<string, string>; // section titles of the version being viewed
  panelOpen: boolean;
  setPanelOpen: (open: boolean) => void;
  panelWidth: number;
  setPanelWidth: (px: number) => void;
  refreshVersions: () => void;
  compareDataset: boolean; // demo: show the dataset's label next to ours (off: the pages look like production)
  setCompareDataset: (on: boolean) => void;
  lastRun: number | null; // demo: the last "Send real postings" run (its batch id)
  setLastRun: (batch: number) => void;
};
const Context = createContext<Shared | null>(null);

export function stored(key: string, fallback: string | null): string | null {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}
export function store(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* only a convenience */
  }
}

// Latest: the newest version that has been published. Previous: the one published before it.
export function tagVersions(versions: Version[]): Tagged[] {
  const published = versions
    .filter((v) => v.published_at)
    .sort((a, b) => Date.parse(b.published_at!) - Date.parse(a.published_at!));
  const latest = published[0]?.name;
  const previous = published[1]?.name;
  return versions.map((v) => ({
    ...v,
    tags: [
      ...(v.name === latest ? (["latest"] as const) : []),
      ...(v.name === previous ? (["previous"] as const) : []),
      ...(v.status === "live" ? (["live"] as const) : []),
    ],
  }));
}

export function SharedProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<User>(() => {
    const u = savedUser();
    setToken(u.token);
    return u;
  });
  const [versions, setVersions] = useState<Tagged[]>([]);
  const [viewing, setViewingState] = useState<string | null>(() => stored("viewing", null));
  const [sections, setSections] = useState<Record<string, string>>({});
  // Open by default on a wide screen; on a phone it would cover the page, so it starts folded.
  const [panelOpen, setPanelOpenState] = useState<boolean>(
    () => stored("panel", window.innerWidth > 900 ? "open" : "folded") === "open",
  );

  const setUser = (u: User) => {
    setToken(u.token);
    saveUser(u);
    setUserState(u);
  };
  const setViewing = (name: string | null) => {
    store("viewing", name);
    setViewingState(name);
  };
  const [panelWidth, setPanelWidthState] = useState<number>(() => Number(stored("panel-width", "280")) || 280);
  const setPanelWidth = (px: number) => {
    const clamped = Math.round(Math.min(480, Math.max(220, px)));
    store("panel-width", String(clamped));
    setPanelWidthState(clamped);
  };
  const setPanelOpen = (open: boolean) => {
    store("panel", open ? "open" : "folded");
    setPanelOpenState(open);
  };

  const [compareDataset, setCompareState] = useState(() => stored("compare-dataset", "off") === "on");
  const setCompareDataset = (on: boolean) => {
    store("compare-dataset", on ? "on" : "off");
    setCompareState(on);
  };
  const [lastRun, setLastRunState] = useState<number | null>(() => Number(stored("live-run", "")) || null);
  const setLastRun = (batch: number) => {
    store("live-run", String(batch));
    setLastRunState(batch);
  };

  const refreshVersions = useCallback(() => {
    api.versions().then((list) => setVersions(tagVersions(list)), () => {});
  }, []);
  useEffect(refreshVersions, [refreshVersions, user]);

  const live = versions.find((v) => v.status === "live")?.name ?? null;
  const latest = versions.find((v) => v.tags.includes("latest"))?.name ?? null;
  const previous = versions.find((v) => v.tags.includes("previous"))?.name ?? null;
  // A viewed version that no longer exists (a reset database) falls back to the live one.
  const shown = viewing && versions.some((v) => v.name === viewing) ? viewing : live;

  useEffect(() => {
    if (!shown) return;
    api.version(shown).then(
      (policy) => setSections(Object.fromEntries(policy.body.sections.map((s: any) => [s.code, s.title]))),
      () => {},
    );
  }, [shown, user]);

  return (
    <Context.Provider
      value={{
        user, setUser, versions, live, latest, previous,
        viewing: shown === live ? null : shown, setViewing,
        sections, panelOpen, setPanelOpen, panelWidth, setPanelWidth, refreshVersions,
        compareDataset, setCompareDataset, lastRun, setLastRun,
      }}
    >
      {children}
    </Context.Provider>
  );
}

export function useShared(): Shared {
  const value = useContext(Context);
  if (!value) throw new Error("useShared outside SharedProvider");
  return value;
}
