// Public account pages: e-mail verification, password reset / invitation, registration, "forgot password".
// Tokens arrive in the URL fragment (#token=...), which browsers never send to the server or to proxies' logs.
import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, errText } from "./api";
import "./styles.css";

const path = location.pathname.replace(/\/+$/, "");
const token = new URLSearchParams(location.hash.slice(1)).get("token") || "";
history.replaceState(null, "", location.pathname);          // remove the token from the address bar

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="center"><div className="card"><h2 style={{ margin: 0 }}>{title}</h2>{children}</div></div>;
}

function Verify() {
  const [state, setState] = useState<"idle" | "ok" | "err">("idle");
  const [msg, setMsg] = useState("");
  return (
    <Shell title="Potwierdzenie adresu e-mail">
      {state === "idle" && <button className="primary" disabled={!token} onClick={() => api("POST", "/api/v1/auth/verify-email", { token })
        .then(() => setState("ok")).catch((e) => { setState("err"); setMsg(errText(e)); })}>Potwierdź adres</button>}
      {state === "ok" && <p data-testid="verified">Adres potwierdzony. Zaloguj się w programie MasterQUO. Konto nie zawiera darmowej licencji – licencję wydaje administrator.</p>}
      {state === "err" && <p className="err">{msg}</p>}
    </Shell>
  );
}

function Reset() {
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <Shell title="Ustaw hasło">
      {done ? <p data-testid="password-set">Hasło ustawione. Wszystkie wcześniejsze sesje zostały wylogowane – zaloguj się ponownie.</p> : (
        <form onSubmit={(e) => {
          e.preventDefault();
          if (pw !== pw2) { setErr("Hasła różnią się."); return; }
          api("POST", "/api/v1/auth/password/reset", { token, new_password: pw }).then(() => setDone(true)).catch((x) => setErr(errText(x)));
        }} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <label className="f">Nowe hasło (min. 12 znaków)<input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} name="password" /></label>
          <label className="f">Powtórz hasło<input type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} name="password2" /></label>
          {err && <div className="err">{err}</div>}
          <button className="primary" disabled={!token}>Zapisz hasło</button>
        </form>)}
    </Shell>
  );
}

function Register() {
  const [f, setF] = useState({ email: "", password: "", display_name: "" });
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <Shell title="Załóż konto MasterQUO">
      <form onSubmit={(e) => { e.preventDefault(); api("POST", "/api/v1/auth/register", { ...f, display_name: f.display_name || null }).then((r) => setMsg(r.message)).catch((x) => setMsg(errText(x))); }}
        style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <label className="f">E-mail<input value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} autoComplete="email" /></label>
        <label className="f">Nazwa (opcjonalnie)<input value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} /></label>
        <label className="f">Hasło (min. 12 znaków)<input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete="new-password" /></label>
        <button className="primary">Zarejestruj</button>
        {msg && <div className="note">{msg}</div>}
        <span className="muted small">Rejestracja nie daje licencji. Po potwierdzeniu e-maila administrator może przypisać Ci licencję 48h.</span>
      </form>
    </Shell>
  );
}

function Forgot() {
  const [email, setEmail] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <Shell title="Nie pamiętam hasła">
      <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="e-mail" />
      <button className="primary" onClick={() => api("POST", "/api/v1/auth/password/forgot", { email }).then((r) => setMsg(r.message)).catch((x) => setMsg(errText(x)))}>Wyślij link</button>
      {msg && <div className="note">{msg}</div>}
    </Shell>
  );
}

const view = path.endsWith("/verify") ? <Verify /> : path.endsWith("/reset") ? <Reset /> : path.endsWith("/forgot") ? <Forgot /> : <Register />;
createRoot(document.getElementById("root")!).render(<StrictMode>{view}</StrictMode>);
