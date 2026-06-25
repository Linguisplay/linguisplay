import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { api, type Me, type Persona, type StoryCard } from "./api";

// Minimal M1 shell: auth gate + a peek at /personas and the Discover feed.
// Real Discover / Chats / Me tabs land in M2+.

export function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Centered>Loading…</Centered>;
  if (!me) return <AuthForm onAuthed={setMe} />;
  return <Home me={me} onLogout={() => api.logout().then(() => setMe(null))} />;
}

function AuthForm({ onAuthed }: { onAuthed: (m: Me) => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [dob, setDob] = useState("2000-01-01");
  const [err, setErr] = useState("");

  async function submit() {
    setErr("");
    try {
      const m =
        mode === "login"
          ? await api.login(email, password)
          : await api.signup(email, password, dob, true);
      onAuthed(m);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <Centered>
      <div style={card}>
        <h1 style={{ marginTop: 0 }}>LinguisPlay</h1>
        <p style={{ color: "#888" }}>{mode === "login" ? "Welcome back" : "Create an account (18+)"}</p>
        <input style={input} placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input style={input} type="password" placeholder="password (8+)" value={password} onChange={(e) => setPassword(e.target.value)} />
        {mode === "signup" && (
          <label style={{ display: "block", fontSize: 13, color: "#888", marginBottom: 8 }}>
            Date of birth
            <input style={input} type="date" value={dob} onChange={(e) => setDob(e.target.value)} />
          </label>
        )}
        {err && <p style={{ color: "#e55" }}>{err}</p>}
        <button style={btn} onClick={submit}>
          {mode === "login" ? "Log in" : "Sign up"}
        </button>
        <p style={{ textAlign: "center", marginBottom: 0 }}>
          <a style={{ cursor: "pointer", color: "#7af" }} onClick={() => setMode(mode === "login" ? "signup" : "login")}>
            {mode === "login" ? "Need an account? Sign up" : "Have an account? Log in"}
          </a>
        </p>
      </div>
    </Centered>
  );
}

function Home({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [stories, setStories] = useState<StoryCard[]>([]);

  useEffect(() => {
    api.listPersonas().then(setPersonas).catch(() => {});
    api.discover().then((p) => setStories(p.items)).catch(() => {});
  }, []);

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: 24, color: "#eee", fontFamily: "system-ui" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong>LinguisPlay</strong>
        <span style={{ fontSize: 13, color: "#888" }}>
          {me.email} ({me.subscription_tier}) · <a style={{ cursor: "pointer", color: "#7af" }} onClick={onLogout}>log out</a>
        </span>
      </header>

      <Section title="My masks (personas)">
        {personas.length === 0 ? (
          <Empty>No personas yet.</Empty>
        ) : (
          personas.map((p) => (
            <div key={p.id} style={row}>
              {p.name} {p.is_default && <Tag>default</Tag>} <span style={{ color: "#888" }}>{p.pronouns}</span>
            </div>
          ))
        )}
        <button style={{ ...btn, marginTop: 8 }} onClick={() => api.createPersona("New mask", "they").then((p) => setPersonas((xs) => [...xs, p]))}>
          + Create mask
        </button>
      </Section>

      <Section title="Discover">
        {stories.length === 0 ? <Empty>No published stories yet.</Empty> : stories.map((s) => (
          <div key={s.id} style={row}>
            <strong>{s.title}</strong>
            <div style={{ color: "#888", fontSize: 13 }}>{s.one_liner}</div>
          </div>
        ))}
      </Section>
    </div>
  );
}

// ── tiny presentational helpers ───────────────────────────
const card: CSSProperties = { background: "#1c1c22", padding: 28, borderRadius: 14, width: 320 };
const input: CSSProperties = { display: "block", width: "100%", padding: 10, margin: "6px 0", borderRadius: 8, border: "1px solid #333", background: "#111", color: "#eee", boxSizing: "border-box" };
const btn: CSSProperties = { width: "100%", padding: 10, borderRadius: 8, border: 0, background: "#5b6cff", color: "white", cursor: "pointer", fontWeight: 600 };
const row: CSSProperties = { padding: "10px 0", borderBottom: "1px solid #2a2a31" };

function Centered({ children }: { children: ReactNode }) {
  return <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "#101014", color: "#eee", fontFamily: "system-ui" }}>{children}</div>;
}
function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ marginTop: 28 }}>
      <h3 style={{ borderBottom: "2px solid #2a2a31", paddingBottom: 6 }}>{title}</h3>
      {children}
    </section>
  );
}
function Empty({ children }: { children: ReactNode }) {
  return <p style={{ color: "#666" }}>{children}</p>;
}
function Tag({ children }: { children: ReactNode }) {
  return <span style={{ fontSize: 11, background: "#5b6cff", padding: "2px 6px", borderRadius: 6 }}>{children}</span>;
}
