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

  // Listing filters, remembered per visitor. Long lists are split across pages,
  // so an active filter searches the whole list (data-scope) instead of one page.
  var form = document.querySelector("[data-filters]");
  var list = document.querySelector("[data-list]");
  if (form && list) {
    var count = form.querySelector("[data-count]");
    var none = document.querySelector("[data-noresults]");
    var pager = document.querySelector(".pager");
    var original = list.innerHTML;
    var originalStart = list.getAttribute("start");
    var scope = list.dataset.scope;
    var KEY = "na-filters";
    var PAGE = 50;
    var data = null;
    var loading = null;
    var limit = PAGE;
    var more = document.createElement("button");
    more.type = "button";
    more.className = "btn btn-ghost more-results";
    more.hidden = true;
    list.parentNode.insertBefore(more, list.nextSibling);

    var esc = function (s) {
      var d = document.createElement("div");
      d.textContent = s == null ? "" : s;
      return d.innerHTML;
    };
    var value = function (name) { return form.elements[name] ? form.elements[name].value : ""; };
    var filtersNow = function () {
      return { ins: value("ins"), cat: value("cat"), zip: value("zip").trim(), g: value("g"),
        tele: form.elements.tele.checked, hi: form.elements.hi.checked };
    };
    var isActive = function (f) { return !!(f.ins || f.cat || f.zip || f.g || f.tele || f.hi); };
    var phone = function (p) { return "(" + p.slice(0, 3) + ") " + p.slice(3, 6) + "-" + p.slice(6); };
    var initials = function (name) {
      var parts = name.match(/[A-Za-z]+/g) || [name];
      return (parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : name.slice(0, 2)).toUpperCase();
    };
    var cardHtml = function (p) {
      var bars = "";
      for (var i = 0; i < 8; i++) bars += '<i class="' + (i < p.k ? "on" : "") + '"></i>';
      var cats = p.t.map(function (c) { return data.cats[c]; }).join(", ");
      var ins = p.i.map(function (k) { return data.payers[k]; }).join(", ");
      var href = "/provider/" + encodeURIComponent(p.s) + "/";
      var title = p.n + (p.c ? ", " + p.c : "");
      return '<li class="card"><span class="mono mono-' + (p.d % 5) + '" aria-hidden="true">' + esc(initials(p.n)) + "</span>" +
        '<div class="card-main"><h2><a href="' + href + '">' + esc(title) + "</a></h2>" +
        '<p class="card-sub">' + esc(cats) + (p.h ? " · Telehealth" : "") + "</p>" +
        '<p class="card-ins"><span class="lamp" aria-hidden="true"></span><span>Listed as accepting with <strong>' + esc(ins) + "</strong></span></p>" +
        '<div class="card-foot"><span class="score score-' + p.l + '"><span class="pips" role="img" aria-label="' + p.k + ' of 8 checks passed">' + bars + "</span>" + esc(data.levels[p.l]) + "</span>" +
        '<p class="card-loc muted">' + esc(p.w) + "</p></div></div>" +
        '<div class="card-act">' + (p.p ? '<a class="btn btn-call" href="tel:+1' + esc(p.p) + '">Call ' + phone(p.p) + "</a>" : "") +
        '<a class="btn btn-ghost" href="' + href + '">Details</a></div></li>';
    };
    var save = function () {
      try {
        var st = {};
        Array.prototype.forEach.call(form.elements, function (el) {
          if (el.name) st[el.name] = el.type === "checkbox" ? el.checked : el.value;
        });
        localStorage.setItem(KEY, JSON.stringify(st));
      } catch (e) {}
    };
    var showOriginal = function () {
      if (list.dataset.mode === "all") {
        list.innerHTML = original;
        if (originalStart) list.setAttribute("start", originalStart);
        list.dataset.mode = "";
      }
      if (pager) pager.hidden = false;
      more.hidden = true;
    };
    var filterPage = function (f) {
      showOriginal();
      var cards = Array.prototype.slice.call(list.querySelectorAll(".card"));
      var shown = 0;
      cards.forEach(function (c) {
        var d = c.dataset;
        var ok = (!f.ins || d.ins.split(" ").indexOf(f.ins) > -1) &&
          (!f.cat || d.cat.split(" ").indexOf(f.cat) > -1) &&
          (!f.zip || d.zip.split(" ").some(function (z) { return z.indexOf(f.zip) === 0; })) &&
          (!f.g || d.g === f.g) && (!f.tele || d.tele === "1") && (!f.hi || d.lvl === "high");
        c.hidden = !ok;
        if (ok) shown++;
      });
      count.textContent = "Showing " + shown + " of " + cards.length + (pager ? " on this page" : "");
      count.classList.toggle("filter-on", isActive(f));
      if (none) none.hidden = shown > 0 || cards.length === 0;
    };
    var filterAll = function (f) {
      var ds = list.dataset;
      var hits = data.providers.filter(function (p) {
        return (!ds.src || p.f.indexOf(ds.src) > -1) && (!ds.fcat || p.t.indexOf(ds.fcat) > -1) &&
          (!ds.fins || p.i.indexOf(ds.fins) > -1) && (!ds.ftele || p.h) &&
          (!f.ins || p.i.indexOf(f.ins) > -1) && (!f.cat || p.t.indexOf(f.cat) > -1) &&
          (!f.zip || p.a.some(function (z) { return z.indexOf(f.zip) === 0; })) &&
          (!f.g || p.g === f.g) && (!f.tele || p.h) && (!f.hi || p.l === "high");
      });
      list.dataset.mode = "all";
      list.setAttribute("start", "1");
      list.innerHTML = hits.slice(0, limit).map(cardHtml).join("");
      if (pager) pager.hidden = true;
      more.hidden = hits.length <= limit;
      more.textContent = "Show more (" + (hits.length - limit) + " left)";
      count.textContent = hits.length.toLocaleString() + (hits.length === 1 ? " match" : " matches") + " across all pages";
      count.classList.add("filter-on");
      if (none) none.hidden = hits.length > 0;
    };
    var apply = function () {
      var f = filtersNow();
      save();
      if (!scope || !isActive(f)) { limit = PAGE; filterPage(f); return; }
      if (data) { filterAll(f); return; }
      filterPage(f);
      count.textContent = "Searching all pages…";
      loading = loading || fetch(scope).then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      });
      loading.then(function (d) {
        data = d;
        var now = filtersNow();
        if (isActive(now)) filterAll(now);
      }).catch(function () {
        scope = null; // the current page still filters without the full list
        filterPage(filtersNow());
      });
    };
    more.addEventListener("click", function () {
      limit += PAGE;
      filterAll(filtersNow());
    });
    try {
      var saved = JSON.parse(localStorage.getItem(KEY) || "{}");
      Object.keys(saved).forEach(function (k) {
        var el = form.elements[k];
        if (!el) return;
        if (el.type === "checkbox") el.checked = !!saved[k]; else el.value = saved[k];
      });
    } catch (e) {}
    form.addEventListener("input", function () { limit = PAGE; apply(); });
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
