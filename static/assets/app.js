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
    var KEY = "po-filters";
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

  // Report / claim forms: prefill NPI. Wire `action` to a form backend before launch.
  var npi = new URLSearchParams(location.search).get("npi");
  document.querySelectorAll("[data-npi], [data-demo-form] input[name=npi]").forEach(function (el) { if (npi) el.value = npi; });
  document.querySelectorAll("[data-demo-form]").forEach(function (f) {
    f.addEventListener("submit", function (ev) {
      if (f.getAttribute("action")) return;
      ev.preventDefault();
      f.querySelector("[data-form-msg]").textContent = "Thanks — received. (Demo: connect a form backend to store submissions.)";
    });
  });
})();
