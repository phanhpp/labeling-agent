// The "acting as" menu: demo users and their bearer tokens (the defaults in .env.example and
// app/auth.py). There is no login page: a local demo picks a user, and the API checks the token's
// role on every request. A cookie sign-in would be the production version.

export type User = { key: string; name: string; role: "viewer" | "editor" | "publisher"; token: string; can: string };

export const USERS: User[] = [
  { key: "viewer", name: "Vic", role: "viewer", token: "demo-viewer", can: "can read" },
  { key: "editor", name: "Eddie", role: "editor", token: "demo-editor", can: "can decide and edit drafts" },
  { key: "publisher_a", name: "Pat", role: "publisher", token: "demo-publisher-a", can: "can also publish" },
  { key: "publisher_b", name: "Sam", role: "publisher", token: "demo-publisher-b", can: "can also publish" },
];

const STORE = "acting-as";

export function savedUser(): User {
  try {
    return USERS.find((u) => u.key === localStorage.getItem(STORE)) ?? USERS[0];
  } catch {
    return USERS[0]; // storage can be blocked; the viewer is the safe default
  }
}

export function saveUser(user: User): void {
  try {
    localStorage.setItem(STORE, user.key);
  } catch {
    /* only a convenience */
  }
}
