// Progressive enhancement only: every page is complete HTML without this file.
(function () {
  // Home search: route to the static category / insurer page.
  var search = document.querySelector("[data-search]");
  if (search) {
    search.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var f = new FormData(search);
      var url = f.get("city") + f.get("cat") + "/" + (f.get("ins") ? f.get("ins") + "/" : "");
      window.location.href = url;
    });
  }

  // Listing filters, remembered per visitor.
  var form = document.querySelector("[data-filters]");
  var list = document.querySelector("[data-list]");
  if (form && list) {
    var cards = Array.prototype.slice.call(list.querySelectorAll(".card"));
    var count = form.querySelector("[data-count]");
    var none = document.querySelector("[data-noresults]");
    var KEY = "na-filters";
    try {
      var saved = JSON.parse(localStorage.getItem(KEY) || "{}");
      Object.keys(saved).forEach(function (k) {
        var el = form.elements[k];
        if (!el) return;
        if (el.type === "checkbox") el.checked = !!saved[k]; else el.value = saved[k];
      });
    } catch (e) {}
    var apply = function () {
      var ins = form.elements.ins ? form.elements.ins.value : "";
      var cat = form.elements.cat ? form.elements.cat.value : "";
      var zip = form.elements.zip.value.trim();
      var g = form.elements.g.value;
      var tele = form.elements.tele.checked;
      var hi = form.elements.hi.checked;
      var shown = 0;
      cards.forEach(function (c) {
        var d = c.dataset;
        var ok = (!ins || d.ins.split(" ").indexOf(ins) > -1) &&
          (!cat || d.cat.split(" ").indexOf(cat) > -1) &&
          (!zip || d.zip.split(" ").some(function (z) { return z.indexOf(zip) === 0; })) &&
          (!g || d.g === g) && (!tele || d.tele === "1") && (!hi || d.lvl === "high");
        c.hidden = !ok;
        if (ok) shown++;
      });
      count.textContent = "Showing " + shown + " of " + cards.length + " on this page";
      if (none) none.hidden = shown > 0 || cards.length === 0;
      try {
        var st = {};
        Array.prototype.forEach.call(form.elements, function (el) {
          if (el.name) st[el.name] = el.type === "checkbox" ? el.checked : el.value;
        });
        localStorage.setItem(KEY, JSON.stringify(st));
      } catch (e) {}
    };
    form.addEventListener("input", apply);
    form.addEventListener("change", apply);
    form.addEventListener("submit", function (ev) { ev.preventDefault(); });
    apply();
  }

  // Copy call script.
  var btn = document.querySelector("[data-copy-btn]");
  if (btn) {
    btn.addEventListener("click", function () {
      var text = document.querySelector("[data-copy]").textContent;
      navigator.clipboard.writeText(text).then(function () { btn.textContent = "Copied"; });
    });
  }

  // Badge page: point each snippet at the provider's own profile (?p=<slug>).
  var codes = document.querySelectorAll("[data-badge-code]");
  if (codes.length) {
    var slug = new URLSearchParams(location.search).get("p") || "";
    var valid = /^[a-z0-9-]+-\d{10}$/.test(slug);
    codes.forEach(function (box) {
      if (valid) box.value = box.value.replace(/href="([^"]*)\/"/, 'href="$1/provider/' + slug + '/"');
      var copy = box.parentNode.querySelector("[data-badge-copy]");
      copy.addEventListener("click", function () {
        navigator.clipboard.writeText(box.value).then(function () { copy.textContent = "Copied"; });
      });
    });
    var note = document.querySelector("[data-badge-note]");
    if (note && valid) note.textContent = "These snippets link to your profile.";
  }

  // Report / claim forms post to the Apps Script endpoint named in <meta name="forms-endpoint">.
  var params = new URLSearchParams(location.search);
  var endpointMeta = document.querySelector('meta[name="forms-endpoint"]');
  var endpoint = endpointMeta && endpointMeta.content;
  document.querySelectorAll("[data-npi], [data-form] input[name=npi]").forEach(function (el) {
    if (params.get("npi")) el.value = params.get("npi");
  });
  document.querySelectorAll("[data-plan]").forEach(function (el) {
    if (/^(free|pro|group)$/.test(params.get("plan") || "")) el.value = params.get("plan");
  });
  // Stripe Payment Links: carry the provider's NPI through checkout.
  if (/^\d{10}$/.test(params.get("npi") || "")) {
    document.querySelectorAll("a[data-pay]").forEach(function (a) {
      a.href += (a.href.indexOf("?") > -1 ? "&" : "?") + "client_reference_id=" + params.get("npi");
    });
  }
  document.querySelectorAll("[data-page]").forEach(function (el) { el.value = document.referrer.slice(0, 200); });
  document.querySelectorAll("[data-form]").forEach(function (f) {
    f.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var msg = f.querySelector("[data-form-msg]");
      var btn = f.querySelector("button[type=submit]");
      if (!/^\d{10}$/.test((f.elements.npi && f.elements.npi.value) || "")) {
        msg.textContent = f.elements.kind.value === "report"
          ? "Open this form from a provider's page using the \u201cI called\u201d button."
          : "Enter the 10-digit NPI number.";
        return;
      }
      if (!endpoint) { msg.textContent = "Submissions aren't connected yet. Please try again later."; return; }
      btn.disabled = true;
      msg.textContent = "Sending\u2026";
      fetch(endpoint, { method: "POST", mode: "no-cors", body: new URLSearchParams(new FormData(f)) })
        .then(function () {
          f.reset();
          msg.textContent = f.elements.kind.value === "report"
            ? "Thank you \u2014 your report will be reflected in this provider\u2019s score within a day."
            : "Thanks \u2014 we\u2019ll be in touch to verify your profile.";
        })
        .catch(function () { msg.textContent = "Couldn't send. Check your connection and try again."; btn.disabled = false; });
    });
  });
})();
