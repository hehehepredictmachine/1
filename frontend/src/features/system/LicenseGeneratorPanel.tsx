// GENERATOR LICENCJI (1.43.0, PMW-LICGEN-1) – narzędzie właściciela: licencje offline podpisane Ed25519, bez logowania.
// GET /api/v1/owner/license/state · POST …/keys (utwórz) · POST …/keys/export · POST …/keys/import · GET …/hwid · POST …/generate ·
// POST …/check · GET /api/v1/owner/licenses · DELETE /api/v1/owner/licenses/{id}. Klucz prywatny zostaje w folderze właściciela
// (%APPDATA%\PepeMarketWizard\owner) – panel pokazuje tylko klucz publiczny; plik prywatny opuszcza dysk wyłącznie przez „Eksportuj kopię”.
import { useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiSend } from "../../api";
import { cls } from "../../util";

type State = { crypto_ok: boolean; crypto_error?: string | null; has_key: boolean; public_key: string | null; key_created?: string | null;
  key_error?: string | null; key_path: string; preset_days: number[]; hwid_format: string };
type Lic = { id: number; user: string; hwid: string | null; iat: number; exp: number | null; iat_iso: string; exp_iso: string | null; note: string;
  key: string; status: string; status_pl: string; perpetual: boolean; signed_with_current_key: boolean };
type Check = { format_ok: boolean; signature_ok: boolean; user: string | null; hwid: string | null; iat_iso: string | null; exp_iso: string | null;
  perpetual: boolean | null; expired: boolean | null; valid: boolean; errors: string[]; this_computer: boolean | null };

const HWID_RE = /^[0-9A-HJKMNP-TV-Z]{5}(-[0-9A-HJKMNP-TV-Z]{5}){3}$/;
const normHwid = (s: string) => s.replace(/\s+/g, "").toUpperCase();
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "");
const errOf = (e: any) => String(e?.message || e);
const FIELDS = ["user", "hwid", "validity", "note", "keys", "key_file", "key", "crypto"];
const splitErr = (e: any): [string, string] => { const m = errOf(e); const i = m.indexOf(": "); const f = m.slice(0, i); return i > 0 && FIELDS.includes(f) ? [f, m.slice(i + 2)] : ["", m]; };

async function copyText(t: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(t); return true; } catch { /* WebView2 bez uprawnień – zapas niżej */ }
  try {
    const ta = document.createElement("textarea"); ta.value = t; ta.style.position = "fixed"; ta.style.opacity = "0"; document.body.appendChild(ta);
    ta.select(); const ok = document.execCommand("copy"); ta.remove(); return ok;
  } catch { return false; }
}
async function pasteText(): Promise<string | null> { try { return await navigator.clipboard.readText(); } catch { return null; } }
async function saveFile(name: string, content: string): Promise<"saved" | "downloaded" | "cancelled"> {
  const w = window as any;
  if (typeof w.showSaveFilePicker === "function") {                       // okno „Zapisz jako” – wybór miejsca zapisu
    try {
      const h = await w.showSaveFilePicker({ suggestedName: name, types: [{ description: "Klucz prywatny Apollo23", accept: { "application/octet-stream": [".key"] } }] });
      const wr = await h.createWritable(); await wr.write(content); await wr.close(); return "saved";
    } catch (e: any) { if (e?.name === "AbortError") return "cancelled"; }
  }
  const url = URL.createObjectURL(new Blob([content], { type: "application/octet-stream" }));
  const a = document.createElement("a"); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 3000);
  return "downloaded";
}

export default function LicenseGeneratorPanel() {
  const [st, setSt] = useState<State | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // klucze
  const [importAsk, setImportAsk] = useState<{ content: string; why: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  // generator
  const [user, setUser] = useState("");
  const [hwid, setHwid] = useState("");
  const [noHwid, setNoHwid] = useState(false);
  const [valid, setValid] = useState<string>("30");                      // "7" | "30" | "90" | "365" | "date" | "perpetual"
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const [ferr, setFerr] = useState<Record<string, string>>({});
  const [made, setMade] = useState<Lic | null>(null);
  const hwidRef = useRef<HTMLInputElement>(null);
  // historia
  const [rows, setRows] = useState<Lic[]>([]);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<[keyof Lic, number]>(["iat", -1]);
  const [delAsk, setDelAsk] = useState<number | null>(null);
  // sprawdzanie
  const [chk, setChk] = useState("");
  const [chkRes, setChkRes] = useState<Check | null>(null);

  const load = () => {
    apiGet<State>("/api/v1/owner/license/state").then((x) => { setSt(x); setLoadErr(null); }).catch((e) => setLoadErr(errOf(e)));
    apiGet<{ licenses: Lic[] }>("/api/v1/owner/licenses").then((x) => setRows(x.licenses || [])).catch(() => setRows([]));
  };
  useEffect(load, []);
  const flash = (m: string) => { setMsg(m); window.setTimeout(() => setMsg((c) => (c === m ? null : c)), 6000); };
  const run = async (fn: () => Promise<any>) => { setBusy(true); try { await fn(); } finally { setBusy(false); } };

  // ------------------------------------------------------------------ klucze
  const createKeys = () => run(async () => {
    try { setSt(await apiSend("POST", "/api/v1/owner/license/keys")); flash("Utworzono parę kluczy. Zrób od razu kopię zapasową klucza prywatnego."); }
    catch (e) { flash("BŁĄD: " + splitErr(e)[1]); }
  });
  const exportKey = () => run(async () => {
    try {
      const r: any = await apiSend("POST", "/api/v1/owner/license/keys/export");
      const how = await saveFile(r.filename, r.content);
      flash(how === "saved" ? "Zapisano kopię klucza prywatnego. Przechowuj ją offline (pendrive, sejf) – kto ma ten plik, może wystawiać licencje."
        : how === "downloaded" ? `Kopia klucza zapisana w folderze pobranych plików (${r.filename}) – przenieś ją w bezpieczne miejsce.` : "Anulowano zapis.");
    } catch (e) { flash("BŁĄD: " + splitErr(e)[1]); }
  });
  const importKey = (content: string, replace: boolean) => run(async () => {
    try {
      const r: any = await apiSend("POST", "/api/v1/owner/license/keys/import", { content, replace });
      setImportAsk(null); setSt(r); load();
      flash(r.same_key ? "Ten klucz jest już zainstalowany – nic nie zmieniono."
        : `Zaimportowano klucz prywatny.${r.previous_key_backup ? " Poprzedni klucz zachowano: " + r.previous_key_backup : ""}`);
    } catch (e) {
      const [f, m] = splitErr(e);
      if (f === "key_file" && /INNY klucz prywatny/.test(m) && !replace) setImportAsk({ content, why: m });
      else flash("BŁĄD importu: " + m);
    }
  });
  const onFile = async (ev: React.ChangeEvent<HTMLInputElement>) => {
    const f = ev.target.files?.[0]; ev.target.value = "";
    if (!f) return;
    if (f.size > 20000) { flash("BŁĄD importu: plik za duży – to nie jest kopia klucza Apollo23."); return; }
    importKey(await f.text(), false);
  };

  // ------------------------------------------------------------------ generator
  const pasteHwid = async () => {
    const t = await pasteText();
    if (t == null) { hwidRef.current?.focus(); flash("Schowek niedostępny – kliknij w pole HWID i naciśnij Ctrl+V."); return; }
    setHwid(normHwid(t)); setNoHwid(false);
  };
  const thisHwid = () => apiGet<any>("/api/v1/owner/license/hwid").then((r) => {
    if (r.hwid) { setHwid(r.hwid); setNoHwid(false); setFerr((x) => ({ ...x, hwid: "" })); } else flash("Nie udało się odczytać HWID: " + (r.error || "brak źródeł"));
  }).catch((e) => flash("BŁĄD: " + errOf(e)));
  const localCheck = (): Record<string, string> => {
    const e: Record<string, string> = {};
    if (!user.trim()) e.user = "podaj nazwę / ID użytkownika";
    if (!noHwid && !HWID_RE.test(normHwid(hwid))) e.hwid = hwid.trim() ? "błędny format HWID – wymagany XXXXX-XXXXX-XXXXX-XXXXX (bez I, L, O, U)" : "podaj HWID albo zaznacz „bez przypisania HWID”";
    if (valid === "date" && (!date || date < today())) e.validity = date ? "data wygaśnięcia jest z przeszłości" : "wybierz datę w kalendarzu";
    return e;
  };
  const generate = () => run(async () => {
    const e = localCheck(); setFerr(e);
    if (Object.keys(e).length) return;
    const validity = valid === "perpetual" ? { kind: "perpetual" } : valid === "date" ? { kind: "date", date } : { kind: "days", days: Number(valid) };
    try {
      const r = await apiSend<Lic>("POST", "/api/v1/owner/license/generate", { user, hwid: noHwid ? null : normHwid(hwid), no_hwid: noHwid, validity, note });
      setMade(r); setFerr({}); load();
    } catch (er) { const [f, m] = splitErr(er); if (f && ["user", "hwid", "validity", "note"].includes(f)) setFerr({ [f]: m }); else flash("BŁĄD: " + m); }
  });

  // ------------------------------------------------------------------ historia
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    const r = rows.filter((x) => !t || [x.user, x.hwid || "bez hwid", x.note, x.status_pl, x.key].some((v) => String(v).toLowerCase().includes(t)));
    const [k, d] = sort;
    return [...r].sort((a, b) => {
      const av: any = k === "exp" ? (a.exp ?? Number.MAX_SAFE_INTEGER) : a[k]; const bv: any = k === "exp" ? (b.exp ?? Number.MAX_SAFE_INTEGER) : b[k];
      return (av ?? "") < (bv ?? "") ? -d : (av ?? "") > (bv ?? "") ? d : 0;
    });
  }, [rows, q, sort]);
  const th = (k: keyof Lic, label: string) => (
    <th aria-sort={sort[0] === k ? (sort[1] > 0 ? "ascending" : "descending") : "none"}>
      <button type="button" className="lic-sort" onClick={() => setSort(([sk, sd]) => [k, sk === k ? -sd : 1])}>{label}{sort[0] === k ? (sort[1] > 0 ? " ▲" : " ▼") : ""}</button></th>);
  const del = (id: number) => run(async () => { try { await apiSend("DELETE", `/api/v1/owner/licenses/${id}`); setDelAsk(null); load(); } catch (e) { flash("BŁĄD: " + errOf(e)); } });

  const check = () => run(async () => { try { setChkRes(await apiSend<Check>("POST", "/api/v1/owner/license/check", { key: chk })); } catch (e) { flash("BŁĄD: " + splitErr(e)[1]); } });

  const noKey = !st?.has_key;
  return (
    <div className="lic" data-testid="license-generator">
      {loadErr && <div className="note bad">Brak połączenia z botem: {loadErr}</div>}
      {st && !st.crypto_ok && <div className="note bad">{st.crypto_error}</div>}
      {msg && <div className="note" role="status">{msg}</div>}

      <section data-testid="lic-keys"><h4>1 · PARA KLUCZY ED25519</h4>
        {st?.key_error && <div className="note bad">{st.key_error}</div>}
        {st && noKey && <>
          <p className="sys-note">Brak kluczy. Klucz prywatny podpisuje licencje i zostaje tylko na tym komputerze ({st.key_path}). Klucz publiczny posłuży później do sprawdzania licencji w aplikacji klienta.</p>
          <div className="lic-btns"><button type="button" className="act on" data-testid="lic-create" disabled={busy || !st.crypto_ok} onClick={createKeys}>UTWÓRZ PARĘ KLUCZY</button>
            <button type="button" className="act" disabled={busy} onClick={() => fileRef.current?.click()}>IMPORTUJ KLUCZ PRYWATNY</button></div></>}
        {st?.has_key && <>
          <div className="field"><span>KLUCZ PUBLICZNY (HEX)</span>
            <div className="lic-keyrow"><code className="lic-mono" data-testid="lic-pub">{st.public_key}</code>
              <button type="button" className="act" onClick={async () => flash((await copyText(st.public_key || "")) ? "Skopiowano klucz publiczny." : "Nie udało się skopiować – zaznacz i Ctrl+C.")}>KOPIUJ</button></div></div>
          <p className="sys-note">Klucz prywatny: {st.key_path}{st.key_created ? ` · utworzony ${when(st.key_created)}` : ""}. Nikomu go nie wysyłaj – kto go ma, może wystawiać licencje.</p>
          <div className="lic-btns"><button type="button" className="act" data-testid="lic-export" disabled={busy} onClick={exportKey}>EKSPORTUJ KOPIĘ ZAPASOWĄ KLUCZA PRYWATNEGO</button>
            <button type="button" className="act" disabled={busy} onClick={() => fileRef.current?.click()}>IMPORTUJ KLUCZ PRYWATNY</button></div></>}
        <input ref={fileRef} type="file" accept=".key,.txt" hidden onChange={onFile} data-testid="lic-import-file" />
        {importAsk && <div className="note bad" role="alertdialog">{importAsk.why}
          <div className="lic-btns"><button type="button" className="act danger" onClick={() => importKey(importAsk.content, true)}>ZASTĄP KLUCZ</button>
            <button type="button" className="act" onClick={() => setImportAsk(null)}>ANULUJ</button></div></div>}
      </section>

      <section data-testid="lic-gen" className={cls(noKey && "lic-off")}><h4>2 · GENERATOR</h4>
        {noKey && <p className="sys-note">Najpierw utwórz albo zaimportuj parę kluczy.</p>}
        <fieldset disabled={noKey || busy} className="lic-form">
          <label className="field"><span>NAZWA / ID UŻYTKOWNIKA</span>
            <input value={user} maxLength={80} onChange={(e) => setUser(e.target.value)} data-testid="lic-user" aria-invalid={!!ferr.user} placeholder="np. Jan Kowalski / klient-042" />
            {ferr.user && <em className="lic-ferr">{ferr.user}</em>}</label>
          <div className="field"><span>HWID KOMPUTERA</span>
            <div className="lic-keyrow"><input ref={hwidRef} value={hwid} disabled={noHwid} onChange={(e) => setHwid(e.target.value.toUpperCase())} onBlur={() => setHwid((h) => normHwid(h))}
              placeholder="XXXXX-XXXXX-XXXXX-XXXXX" maxLength={29} className="lic-mono" data-testid="lic-hwid" aria-invalid={!!ferr.hwid} />
              <button type="button" className="act" disabled={noHwid} onClick={pasteHwid}>WKLEJ</button>
              <button type="button" className="act" disabled={noHwid} onClick={thisHwid} data-testid="lic-this-hwid">UŻYJ HWID TEGO KOMPUTERA</button></div>
            <label className="lic-check"><input type="checkbox" checked={noHwid} onChange={(e) => { setNoHwid(e.target.checked); setFerr((x) => ({ ...x, hwid: "" })); }} data-testid="lic-nohwid" /> bez przypisania HWID (działa na każdym komputerze)</label>
            {ferr.hwid && <em className="lic-ferr">{ferr.hwid}</em>}</div>
          <div className="field"><span>WAŻNOŚĆ</span>
            <div className="lic-btns" role="radiogroup" aria-label="Ważność">{[...(st?.preset_days || [7, 30, 90, 365]).map((d) => [String(d), `${d} DNI`]), ["date", "WŁASNA DATA"], ["perpetual", "BEZTERMINOWA"]].map(([k, l]) => (
              <button key={k} type="button" role="radio" aria-checked={valid === k} className={cls("act", valid === k && "on")} data-testid={"lic-valid-" + k} onClick={() => setValid(k)}>{l}</button>))}</div>
            {valid === "date" && <input type="date" value={date} min={today()} onChange={(e) => setDate(e.target.value)} data-testid="lic-date" aria-label="Data wygaśnięcia" />}
            {valid === "date" && <small className="lic-hint">Licencja wygasa o 23:59:59 wybranego dnia (czas tego komputera).</small>}
            {ferr.validity && <em className="lic-ferr">{ferr.validity}</em>}</div>
          <label className="field"><span>NOTATKA (OPCJONALNIE – TYLKO W HISTORII, NIE W KLUCZU)</span>
            <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} data-testid="lic-note" />
            {ferr.note && <em className="lic-ferr">{ferr.note}</em>}</label>
          <button type="button" className="ptc-big" data-testid="lic-generate" onClick={generate}>GENERUJ</button>
        </fieldset>
        {made && <div className="lic-out" data-testid="lic-result">
          <div className="field"><span>KLUCZ LICENCJI · {made.user} · {made.hwid || "bez HWID"} · {made.perpetual ? "bezterminowa" : "do " + when(made.exp_iso)}</span>
            <textarea readOnly value={made.key} rows={3} className="lic-mono" onFocus={(e) => e.currentTarget.select()} data-testid="lic-key-out" /></div>
          <button type="button" className="act on" onClick={async () => flash((await copyText(made.key)) ? "Skopiowano klucz licencji." : "Nie udało się skopiować – zaznacz klucz i Ctrl+C.")}>KOPIUJ KLUCZ</button></div>}
      </section>

      <section data-testid="lic-history"><h4>3 · HISTORIA LICENCJI ({rows.length})</h4>
        <input className="lic-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Szukaj: użytkownik, HWID, notatka, status…" aria-label="Szukaj w historii" data-testid="lic-search" />
        {shown.length ? (
          <div className="lic-tblwrap"><table className="sys-tbl lic-tbl"><thead><tr>{th("user", "UŻYTKOWNIK")}{th("hwid", "HWID")}{th("iat", "WYDANA")}{th("exp", "WYGASA")}{th("status", "STATUS")}{th("note", "NOTATKA")}<th /></tr></thead>
            <tbody>{shown.map((r) => (
              <tr key={r.id} data-testid={"lic-row-" + r.id}><td>{r.user}</td><td className="lic-mono">{r.hwid || <i className="dim">bez HWID</i>}</td><td>{when(r.iat_iso)}</td>
                <td>{r.perpetual ? "bezterminowa" : when(r.exp_iso)}</td>
                <td><span className={cls("sys-st", r.status === "AKTYWNA" ? "ok" : "bad")}>{r.status_pl}</span>{!r.signed_with_current_key && <span className="sys-st warn" title="Wydana innym kluczem prywatnym niż obecny">inny klucz</span>}</td>
                <td className="lic-note">{r.note}</td>
                <td className="lic-acts"><button type="button" className="act" onClick={async () => flash((await copyText(r.key)) ? `Skopiowano klucz: ${r.user}.` : "Nie udało się skopiować.")}>KOPIUJ</button>
                  {delAsk === r.id ? <><button type="button" className="act danger" onClick={() => del(r.id)}>USUŃ WPIS</button><button type="button" className="act" onClick={() => setDelAsk(null)}>NIE</button></>
                    : <button type="button" className="act" aria-label={"Usuń wpis: " + r.user} onClick={() => setDelAsk(r.id)}>✕</button>}</td></tr>))}</tbody></table></div>
        ) : <p className="sys-note">{rows.length ? "Brak wyników wyszukiwania." : "Brak wydanych licencji."}</p>}
        <p className="sys-note">Usunięcie wpisu nie unieważnia klucza – licencja offline działa do daty wygaśnięcia.</p>
      </section>

      <section data-testid="lic-check"><h4>4 · SPRAWDŹ KLUCZ</h4>
        <textarea value={chk} onChange={(e) => setChk(e.target.value)} rows={3} placeholder="Wklej klucz PMW1-…" className="lic-mono lic-chk" data-testid="lic-check-in" />
        <button type="button" className="act" disabled={!chk.trim() || busy} onClick={check} data-testid="lic-check-btn">SPRAWDŹ</button>
        {chkRes && <dl className="sys-kv lic-res" data-testid="lic-check-out">
          <dt>Wynik</dt><dd><span className={cls("sys-st", chkRes.valid ? "ok" : "bad")}>{chkRes.valid ? "KLUCZ WAŻNY" : "KLUCZ NIEWAŻNY"}</span></dd>
          <dt>Podpis</dt><dd><span className={cls("sys-st", chkRes.signature_ok ? "ok" : "bad")}>{chkRes.signature_ok ? "POPRAWNY" : "NIEPRAWIDŁOWY"}</span></dd>
          <dt>Użytkownik</dt><dd>{chkRes.user ?? "—"}</dd>
          <dt>HWID</dt><dd className="lic-mono">{chkRes.hwid ?? (chkRes.format_ok ? "bez przypisania" : "—")}{chkRes.this_computer != null && <i className="dim"> · {chkRes.this_computer ? "ten komputer" : "inny komputer"}</i>}</dd>
          <dt>Wydana</dt><dd>{when(chkRes.iat_iso) || "—"}</dd>
          <dt>Wygasa</dt><dd>{chkRes.perpetual ? "bezterminowa" : chkRes.exp_iso ? `${when(chkRes.exp_iso)}${chkRes.expired ? " · WYGASŁA" : ""}` : "—"}</dd>
          {!!chkRes.errors.length && <><dt>Uwagi</dt><dd className="bad">{chkRes.errors.join(" · ")}</dd></>}</dl>}
      </section>
    </div>);
}
