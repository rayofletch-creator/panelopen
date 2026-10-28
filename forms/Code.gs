// Google Apps Script that writes to the "Now Accepting submissions" Sheet.
// Deploy: Deploy -> New deployment -> Web app, Execute as: Me, Who has access: Anyone.
// POST receives form submissions; GET returns anonymous report counts per NPI
// for the site build. Claim emails never leave the Sheet.

const SPREADSHEET_ID = "1CWofeSoq7nQOjkcoxztZdXIlZg7sB8RJ5Ai29fEnlHk";
const SHEETS = {
  report: ["received", "npi", "outcome", "wait", "page"],
  claim: ["received", "npi", "email", "plan"],
};
const OUTCOMES = ["yes", "waitlist", "no", "oon", "wrong"];

function doPost(e) {
  const p = (e && e.parameter) || {};
  if (p.website) return ok_(); // honeypot: only bots fill the hidden field
  if (!SHEETS[p.kind] || !/^\d{10}$/.test(p.npi || "")) return ok_();
  if (p.kind === "report") {
    if (OUTCOMES.indexOf(p.o) < 0) return ok_();
    sheet_("report").appendRow([new Date(), "'" + p.npi, p.o, (p.wait || "").slice(0, 20), (p.page || "").slice(0, 200)]);
  } else {
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(p.email || "")) return ok_();
    sheet_("claim").appendRow([new Date(), "'" + p.npi, p.email.slice(0, 200), (p.plan || "").slice(0, 20)]);
  }
  return ok_();
}

function doGet() {
  const rows = sheet_("report").getDataRange().getValues().slice(1);
  const cutoff = Date.now() - 90 * 864e5;
  const out = {};
  rows.forEach(function (r) {
    const t = new Date(r[0]).getTime();
    if (!(t >= cutoff)) return;
    const npi = String(r[1]).replace(/\D/g, "");
    const a = (out[npi] = out[npi] || { yes: 0, waitlist: 0, no: 0, oon: 0, wrong: 0, last: "" });
    if (a[r[2]] !== undefined) a[r[2]]++;
    const d = new Date(t).toISOString().slice(0, 10);
    if (d > a.last) a.last = d;
  });
  return ContentService.createTextOutput(JSON.stringify(out)).setMimeType(ContentService.MimeType.JSON);
}

function sheet_(name) {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  let s = ss.getSheetByName(name);
  if (!s) {
    s = ss.insertSheet(name);
    s.appendRow(SHEETS[name]);
    s.setFrozenRows(1);
  }
  return s;
}

function ok_() {
  return ContentService.createTextOutput('{"ok":true}').setMimeType(ContentService.MimeType.JSON);
}
