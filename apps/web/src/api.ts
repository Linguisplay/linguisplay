// Thin typed client over the LinguisPlay API (contract v0).
// credentials: "include" so the httpOnly lp_session cookie rides along.

const BASE = "/api/v1";

export interface Me {
  id: string;
  email: string;
  display_name?: string | null;
  avatar_url?: string | null;
  subscription_tier: string;
}

export interface Persona {
  id: string;
  name: string;
  pronouns?: string | null;
  tagline?: string | null;
  background?: string | null;
  is_default: boolean;
}

export interface StoryCard {
  id: string;
  title: string;
  cover_url?: string | null;
  one_liner?: string | null;
  trope_tags: string[];
}

export interface StoryCardPage {
  items: StoryCard[];
  next_cursor: string | null;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || body.error || `${res.status} ${res.statusText}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  signup: (email: string, password: string, dob: string, accepted_tos: boolean) =>
    req<Me>("/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password, dob, accepted_tos }),
    }),
  login: (email: string, password: string) =>
    req<Me>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => req<void>("/auth/logout", { method: "POST" }),
  me: () => req<Me>("/me"),

  listPersonas: () => req<Persona[]>("/personas"),
  createPersona: (name: string, pronouns?: string) =>
    req<Persona>("/personas", { method: "POST", body: JSON.stringify({ name, pronouns }) }),

  discover: () => req<StoryCardPage>("/stories"),
};
