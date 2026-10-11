"use strict";
// MasterQUO license administration panel. No secrets are kept in JS state beyond the CSRF token of this tab;
// the session cookie is HttpOnly. A newly generated license key is shown ONCE and is not stored anywhere.
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const ERR = {
  LOGIN_FAILED: "Nieprawidłowy e-mail, hasło lub kod (po 5 błędach konto blokuje się na 15 min).",
  RATE_LIMITED: "Za dużo prób – odczekaj chwilę.", NOT_AUTHENTICATED: "Sesja wygasła – zaloguj się ponownie.",
  FORBIDDEN_ROLE: "Twoja rola (VIEWER) pozwala tylko na podgląd.", CSRF_INVALID: "Odśwież stronę (token CSRF).",
  ORIGIN_NOT_ALLOWED: "Żądanie z niedozwolonego adresu.", REASON_REQUIRED: "Podaj powód.", ALREADY_REVOKED: "Licencja już cofnięta.",
  SERVER_CLOCK_ANOMALY: "Wykryto anomalię zegara serwera – wydawanie licencji wstrzymane (CLI: clock-ack).",
  PASSWORD_WEAK: "Hasło za słabe (min. 12 znaków).", CUSTOMER_NOT_FOUND: "Nie znaleziono klienta.",
};
let csrf = null, me = null, tab = "dash", skew = 0, timer = null, page = 1, filt = { q: "", status: "" };

async function api(path, body) {
  const opt = { method: body === undefined ? "GET" : "POST", credentials: "same-origin", headers: {} };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.headers["X-CSRF"] = csrf || ""; opt.body = JSON.stringify(body); }
  const r = await fetch("/api/v1" + path, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(ERR[j.error] || j.error || ("HTTP " + r.status)); e.code = j.error; e.status = r.status; throw e; }
  return j;
}
const ts = (t) => t ? new Date(t * 1000).toISOString().replace("T", " ").slice(0, 19) + " UTC" : "–";
const left = (s) => s <= 0 ? "0" : `${Math.floor(s / 3600)} h ${String(Math.floor(s % 3600 / 60)).padStart(2, "0")} min`;
const nowS = () => Math.floor(Date.now() / 1000) + skew;
const canWrite = () => me && me.role === "ADMIN";
const STL = { AKTYWNA: "aktywna", WYGASLA: "wygasła", COFNIETA: "cofnięta", ZAKONCZONA: "zakończona", WYGASLA_DZIERZAWA: "dzierżawa wygasła" };

function loginView(msg) {
  $("#who").textContent = "";
  $("#app").innerHTML = `<div class="card login"><h2>Logowanie administratora</h2>
   <form id="lf"><label>E-mail<input name="email" type="email" autocomplete="username" required></label>
   <label>Hasło<input name="password" type="password" autocomplete="current-password" required></label>
   <label>Kod z aplikacji TOTP lub kod odzyskiwania<input name="code" autocomplete="one-time-code" required></label>
   <button class="primary" data-testid="login">Zaloguj</button> <span class="err" id="le">${esc(msg || "")}</span></form>
   <p class="mut">Konta administratorów tworzy się wyłącznie poleceniem CLI na serwerze (bootstrap-admin / add-admin).</p></div>`;
  $("#lf").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      const r = await api("/admin/login", { email: f.get("email"), password: f.get("password"), code: f.get("code") });
      csrf = r.csrf; me = r.admin; render();
    } catch (er) { $("#le").textContent = er.message; }
  };
}

async function boot() {
  try { const r = await api("/admin/me"); csrf = r.csrf; me = r.admin; skew = r.server_time - Math.floor(Date.now() / 1000); render(); }
  catch { loginView(); }
}

function nav() {
  const tabs = [["dash", "Podsumowanie"], ["lic", "Licencje"], ["ses", "Sesje"], ["cus", "Klienci"], ["tel", "Statystyki (opt-in)"], ["aud", "Audyt"], ["acc", "Konto"]];
  return `<nav>${tabs.map(([k, l]) => `<button data-tab="${k}" class="${tab === k ? "on" : ""}">${l}</button>`).join("")}
   <button id="lo" class="push">Wyloguj</button></nav><div id="body"></div>`;
}

async function render() {
  $("#who").textContent = `${me.email} (${me.role})`;
  $("#app").innerHTML = nav();
  document.querySelectorAll("nav [data-tab]").forEach((b) => b.onclick = () => { tab = b.dataset.tab; render(); });
  $("#lo").onclick = async () => { try { await api("/admin/logout", {}); } catch { } csrf = me = null; loginView(); };
  try { await ({ dash, lic, ses, cus, tel, aud, acc })[tab]($("#body")); }
  catch (e) { if (e.status === 401) loginView(e.message); else $("#body").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}

async function dash(el) {
  const s = await api("/admin/summary");
  skew = s.server_time - Math.floor(Date.now() / 1000);
  const k = (v, l) => `<div class="card kpi"><b>${esc(v)}</b><span>${l}</span></div>`;
  el.innerHTML = `<div class="grid">${k(s.licenses_active, "licencje aktywne")}${k(s.expiring_6h, "wygasają w ≤ 6 h")}${k(s.sessions_active, "aktywne sesje bota")}
   ${k(s.created_24h, "wygenerowane w 24 h")}${k(s.licenses_expired, "wygasłe")}${k(s.licenses_revoked, "cofnięte")}${k(s.denied_24h, "odmowy w 24 h")}${k(s.customers, "klienci")}</div>
   <div class="card mut">Czas serwera (UTC): ${ts(s.server_time)} · licencja trwa ${s.license_seconds / 3600} h od wygenerowania · dzierżawa sesji ${s.lease_seconds} s ·
   klucz podpisu: ${esc(s.kid)} · migracje bazy: ${esc((s.db_migrations || []).join(", "))} ${s.clock_anomaly ? `<b class="err">ANOMALIA ZEGARA: ${esc(s.clock_anomaly)}</b>` : `<span class="st-OK">usługa działa</span>`}</div>
   <div class="card wrap"><h3>Ostatnie zdarzenia</h3><table><tbody>${(s.recent_events || []).map((a) => `<tr><td>${ts(a.at)}</td><td>${esc(a.actor)}</td><td>${esc(a.action)}</td>
   <td class="${a.result === "OK" ? "st-OK" : "err"}">${esc(a.result)}</td></tr>`).join("") || `<tr><td class="mut">Brak zdarzeń.</td></tr>`}</tbody></table></div>`;
}

async function lic(el) {
  const listUrl = () => `/admin/licenses?page=${page}&per_page=50&q=${encodeURIComponent(filt.q)}&status=${encodeURIComponent(filt.status)}`;
  const [first, { customers }] = await Promise.all([api(listUrl()), api("/admin/customers")]);
  const copt = `<option value="">— bez klienta —</option>` + customers.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("");
  el.innerHTML = `${canWrite() ? `<div class="card"><h3>Nowa licencja (72 h od wygenerowania)</h3><form class="row" id="nf">
     <label>Klient<select name="customer_id">${copt}</select></label><label>Notatka<input name="note" maxlength="500"></label>
     <label>Jednoczesne sesje<input name="max_sessions" type="number" min="1" max="10" value="1" class="w80"></label>
     <button class="primary" data-testid="gen">Generuj</button></form><div id="newkey"></div></div>` : ""}
   <div class="card"><form class="row" id="ff"><label>Szukaj (klient, notatka, końcówka klucza)<input name="q" value="${esc(filt.q)}"></label><label>Status<select name="status"><option value="">wszystkie</option>
     ${["AKTYWNA", "WYGASLA", "COFNIETA"].map((x) => `<option ${filt.status === x ? "selected" : ""}>${x}</option>`).join("")}</select></label><button>Filtruj</button>
     <span id="pg" class="mut"></span><button type="button" id="prev">‹</button><button type="button" id="next">›</button></form></div>
   <div class="card wrap"><table data-testid="lic-table"><thead><tr><th>Klucz</th><th>Status</th><th>Pozostało</th><th>Klient / notatka</th><th>Wygenerowana</th><th>Wygasa</th><th>Pierwsze / ostatnie użycie</th><th>Sesje</th><th></th></tr></thead>
   <tbody id="lt"></tbody></table></div>`;
  const fill = (res) => {
    const rows = res.licenses;
    $("#pg").textContent = `strona ${res.page} z ${Math.max(1, Math.ceil(res.total / res.per_page))} (${res.total})`;
    $("#prev").disabled = res.page <= 1; $("#next").disabled = res.page * res.per_page >= res.total;
    $("#lt").innerHTML = rows.map((l) => `<tr data-id="${esc(l.id)}"><td>${esc(l.key_hint)}${l.replaces ? `<br><span class="mut">zastępuje ${esc(l.replaces.slice(0, 8))}</span>` : ""}</td>
      <td class="st-${l.status}">${STL[l.status] || l.status}${l.revoke_reason ? `<br><span class="mut">${esc(l.revoke_reason)}</span>` : ""}</td>
      <td data-exp="${l.status === "AKTYWNA" ? l.expires_at : 0}">${l.status === "AKTYWNA" ? left(l.expires_at - nowS()) : "–"}</td>
      <td>${esc(l.customer_name || "–")}<br><span class="mut">${esc(l.note || "")}</span></td><td>${ts(l.created_at)}</td><td>${ts(l.expires_at)}</td><td>${ts(l.first_used_at)}<br>${ts(l.last_used_at)}</td>
      <td>${l.active_sessions}/${l.max_sessions}${canWrite() ? ` <button data-act="maxs" title="Zmień limit jednoczesnych sesji">±</button>` : ""}</td><td>${canWrite() && l.status !== "COFNIETA" ? `<button data-act="revoke" class="danger">Cofnij</button> ` : ""}
      ${canWrite() ? `<button data-act="reissue">Wydaj ponownie</button> <select data-act="assign"><option value="">przypisz…</option>${copt}</select>` : ""}</td></tr>`).join("")
      || `<tr><td colspan="9" class="mut">Brak licencji.</td></tr>`;
  };
  fill(first);
  $("#ff").onsubmit = async (e) => { e.preventDefault(); const f = new FormData(e.target); filt = { q: f.get("q") || "", status: f.get("status") || "" }; page = 1; fill(await api(listUrl())); };
  $("#prev").onclick = async () => { page = Math.max(1, page - 1); fill(await api(listUrl())); };
  $("#next").onclick = async () => { page += 1; fill(await api(listUrl())); };
  if ($("#nf")) $("#nf").onsubmit = async (e) => {
    e.preventDefault(); const f = new FormData(e.target);
    try {
      const r = await api("/admin/licenses", { customer_id: f.get("customer_id") || null, note: f.get("note") || null, max_sessions: Number(f.get("max_sessions") || 1) });
      showKey(r);
    } catch (er) { $("#newkey").innerHTML = `<p class="err">${esc(er.message)}</p>`; }
  };
  $("#lt").onclick = async (e) => {
    const b = e.target.closest("button[data-act]"); if (!b) return;
    const id = b.closest("tr").dataset.id;
    if (b.dataset.act === "maxs") {
      const n = Number(prompt("Limit jednoczesnych sesji (1–10):", "1"));
      if (!n) return;
      try { await api(`/admin/licenses/${id}/max-sessions`, { max_sessions: n }); fill(await api(listUrl())); } catch (er) { alert(er.message); }
      return;
    }
    const reason = prompt(b.dataset.act === "revoke" ? "Powód cofnięcia licencji:" : "Powód ponownego wydania (stary klucz zostanie cofnięty):");
    if (!reason) return;
    try {
      const r = await api(`/admin/licenses/${id}/${b.dataset.act}`, { reason });
      if (b.dataset.act === "reissue") { showKey(r); fill(await api(listUrl())); } else render();
    } catch (er) { alert(er.message); }
  };
  $("#lt").onchange = async (e) => {
    const s = e.target.closest("select[data-act=assign]"); if (!s || !s.value) return;
    try { await api(`/admin/licenses/${s.closest("tr").dataset.id}/assign`, { customer_id: s.value }); render(); } catch (er) { alert(er.message); }
  };
}

function showKey(r) {
  const box = $("#newkey") || $("#body");
  box.innerHTML = `<p><b>Klucz licencji – widoczny tylko teraz.</b> Przekaż go klientowi bezpiecznym kanałem; serwer przechowuje wyłącznie skrót HMAC.</p>
   <div class="key" data-testid="new-key">${esc(r.key)}</div><p class="mut">Ważna do ${ts(r.expires_at)} (72 h od wygenerowania). <button id="cp">Kopiuj</button></p>`;
  $("#cp").onclick = () => navigator.clipboard && navigator.clipboard.writeText(r.key);
}

async function ses(el) {
  const { sessions } = await api("/admin/sessions?active_only=false");
  el.innerHTML = `<div class="card wrap"><table><thead><tr><th>Licencja</th><th>Stan</th><th>Start</th><th>Ostatni kontakt</th><th>Wersja / etykieta</th><th>IP</th><th>Powód końca</th><th></th></tr></thead><tbody id="st">
   ${sessions.map((s) => `<tr data-id="${esc(s.id)}"><td>${esc(s.key_hint)}</td><td class="st-${s.state}">${STL[s.state] || s.state}</td><td>${ts(s.created_at)}</td><td>${ts(s.last_seen_at)}</td>
   <td>${esc(s.client_version)} ${esc(s.client_label)}</td><td>${esc(s.ip)}</td><td>${esc(s.end_reason || "")}</td>
   <td>${canWrite() && !s.ended_at ? `<button class="danger" data-act="term">Zakończ</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="8" class="mut">Brak sesji.</td></tr>`}</tbody></table>
   <p class="mut">Zakończenie sesji lub cofnięcie licencji dociera do bota przy najbliższym odnowieniu dzierżawy (≤ 30 s). Otwarte pozycje i ich SL/TP nie są zamykane.</p></div>`;
  $("#st").onclick = async (e) => {
    const b = e.target.closest("button[data-act=term]"); if (!b || !confirm("Zakończyć tę sesję bota?")) return;
    try { await api(`/admin/sessions/${b.closest("tr").dataset.id}/terminate`, {}); render(); } catch (er) { alert(er.message); }
  };
}

async function cus(el) {
  const { customers } = await api("/admin/customers");
  el.innerHTML = `${canWrite() ? `<div class="card"><h3>Nowy klient</h3><form class="row" id="cf"><label>Nazwa<input name="name" required maxlength="120"></label>
   <label>E-mail<input name="email" maxlength="200"></label><label>Login MT5<input name="mt5_login" maxlength="40"></label><label>Notatka<input name="note"></label>
   <label><span><input type="checkbox" name="stats_allowed"> zgoda na statystyki</span></label><button class="primary">Dodaj</button></form></div>` : ""}
   <div class="card wrap"><table><thead><tr><th>Nazwa</th><th>E-mail</th><th>Login MT5</th><th>Licencje (aktywne/wszystkie)</th><th>Statystyki</th><th>Notatka</th></tr></thead><tbody>
   ${customers.map((c) => `<tr><td>${esc(c.name)}</td><td>${esc(c.email || "")}</td><td>${esc(c.mt5_login || "")}</td><td>${c.licenses_active}/${c.licenses_total}</td>
   <td>${c.stats_allowed ? "zgoda" : "brak zgody"}</td><td>${esc(c.note || "")}</td></tr>`).join("") || `<tr><td colspan="6" class="mut">Brak klientów.</td></tr>`}</tbody></table></div>`;
  if ($("#cf")) $("#cf").onsubmit = async (e) => {
    e.preventDefault(); const f = new FormData(e.target);
    try { await api("/admin/customers", { name: f.get("name"), email: f.get("email") || null, mt5_login: f.get("mt5_login") || null, note: f.get("note") || null, stats_allowed: !!f.get("stats_allowed") }); render(); }
    catch (er) { alert(er.message); }
  };
}

async function tel(el) {
  const { telemetry } = await api("/admin/telemetry");
  el.innerHTML = `<div class="card wrap"><p class="mut">Tylko dane wysłane przez bota za zgodą użytkownika (opcja w kliencie) i dla klientów ze zgodą na statystyki. Wartości liczone przez bota po kosztach; serwer ich nie weryfikuje.</p>
   <table><thead><tr><th>Licencja</th><th>Klient</th><th>Odebrano</th><th>Tryb</th><th>Balance / equity</th><th>Transakcje</th><th>Winrate netto %</th><th>PF netto</th><th>E[R]</th><th>ROI %</th><th>Okres / źródło / stan na</th></tr></thead><tbody>
   ${telemetry.map((t) => `<tr><td>${esc(t.key_hint)}</td><td>${esc(t.customer_name || "")}</td><td>${ts(t.at)}</td><td>${esc(t.execution_mode || "")}</td><td>${t.balance != null ? `${esc(t.balance)} / ${esc(t.equity ?? "–")} ${esc(t.currency || "")}` : "brak danych"}</td><td>${esc(t.trades_closed ?? "–")}</td>
   <td>${esc(t.winrate_net_pct ?? "–")}</td><td>${esc(t.profit_factor_net ?? "–")}</td><td>${esc(t.expectancy_r ?? "–")}</td><td>${esc(t.roi_pct ?? "–")}</td>
   <td>${esc(t.period || "–")} / ${esc(t.stats_source || "–")} / ${esc(t.stats_as_of || "–")}${nowS() - t.at > 120 ? ' <b class="err">nieaktualne</b>' : ""}</td></tr>`).join("") || `<tr><td colspan="11" class="mut">Brak danych (brak połączenia = brak danych, nie zero).</td></tr>`}</tbody></table></div>`;
}

async function aud(el) {
  const { audit } = await api("/admin/audit");
  el.innerHTML = `<div class="card wrap"><table><thead><tr><th>Czas</th><th>Kto</th><th>Akcja</th><th>Wynik</th><th>Obiekt</th><th>Szczegóły</th><th>IP</th></tr></thead><tbody>
   ${audit.map((a) => `<tr><td>${ts(a.at)}</td><td>${esc(a.actor)}</td><td>${esc(a.action)}</td><td class="${a.result === "OK" ? "st-OK" : "err"}">${esc(a.result)}</td>
   <td>${esc(a.target_type || "")} ${esc((a.target_id || "").slice(0, 8))}</td><td class="mut">${esc(a.detail_json || "")}</td><td>${esc(a.ip || "")}</td></tr>`).join("")}</tbody></table></div>`;
}

async function acc(el) {
  el.innerHTML = `<div class="card"><h3>Zmiana hasła</h3><form class="row" id="pf"><label>Obecne<input type="password" name="c" autocomplete="current-password" required></label>
   <label>Nowe (min. 12)<input type="password" name="n" autocomplete="new-password" required></label><button class="primary">Zmień</button> <span id="pm"></span></form>
   <p class="mut">Reset MFA i dodawanie administratorów: tylko CLI na serwerze (python -m mqlicense reset-mfa / add-admin).</p></div>`;
  $("#pf").onsubmit = async (e) => {
    e.preventDefault(); const f = new FormData(e.target);
    try { await api("/admin/password", { current_password: f.get("c"), new_password: f.get("n") }); $("#pm").textContent = "Zmieniono."; }
    catch (er) { $("#pm").textContent = er.message; }
  };
}

function tick() {
  $("#clock").textContent = ts(nowS());
  document.querySelectorAll("td[data-exp]").forEach((td) => { const e = Number(td.dataset.exp); if (e) td.textContent = left(e - nowS()); });
}
timer = setInterval(tick, 1000);
boot();
