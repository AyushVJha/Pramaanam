/* Pramaan front end. Plain JavaScript, no libraries, no third-party requests.
   Every value from the server is put on the page with textContent, never innerHTML. */
(() => {
  "use strict";

  const STATUS = {
    VERIFIED: ["ok", "Verified"],
    NEEDS_REVIEW: ["review", "Needs review"],
    MISQUOTE: ["bad", "Misquote"],
    NAME_MISMATCH: ["bad", "Name mismatch"],
    WRONG_PARAGRAPH: ["bad", "Wrong paragraph"],
    UNSUPPORTED: ["bad", "Unsupported"],
    CONTRADICTED: ["bad", "Contradicted"],
    LOW_FIDELITY_SOURCE: ["noise", "Scan noise in source"],
    NOT_FOUND_IN_CORPUS: ["none", "Not in corpus"],
    CANNOT_VERIFY: ["none", "Cannot verify"],
  };
  const ORDER = ["VERIFIED", "NEEDS_REVIEW", "MISQUOTE", "NAME_MISMATCH", "WRONG_PARAGRAPH",
    "UNSUPPORTED", "CONTRADICTED", "LOW_FIDELITY_SOURCE", "CANNOT_VERIFY", "NOT_FOUND_IN_CORPUS"];
  const COLOUR = { ok: "--ok", review: "--review", bad: "--bad", none: "--none", noise: "--noise" };

  const SAMPLE = [
    "WRITTEN SUBMISSIONS ON BEHALF OF THE APPELLANT",
    "",
    "1. The appellant relies on Deepak Ananda Patil v. State of Maharashtra, 2023 INSC 11, para 14, where this Court observed: \"The second limb of the submission of Dr Singhvi is that there are concurrent findings in the order of the\".",
    "",
    "2. The same judgment is said to hold that \"The second limb of the submission of Dr Singhvi is not that there are concurrent findings in the order of the\" (Deepak Ananda Patil v. State of Maharashtra, 2023 INSC 11).",
    "",
    "3. Reliance is placed on Kumar Industries v. Union of India, 2023 INSC 11, for the proposition that concurrent findings bind this Court.",
    "",
    "4. The appellant further relies on Municipal Corporation of the City of Ahmedabad v. State of Gujarat, [1973] 1 S.C.R. 1, for the proposition that a municipal body derives its powers from statute.",
    "",
    "5. Finally, the respondent's reliance on Imaginary Holdings v. Union of India, 2023 INSC 99999, is misplaced.",
  ].join("\n");

  const $ = (sel, root = document) => root.querySelector(sel);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  const form = $("#check-form");
  const fileInput = $("#file-input");
  const drop = $("#drop");
  const textInput = $("#text-input");
  const checkBtn = $("#check-btn");
  const errorBox = $("#error");
  const results = $("#results");
  const tabs = [$("#tab-file"), $("#tab-text")];
  const panels = { "tab-file": $("#panel-file"), "tab-text": $("#panel-text") };

  let mode = "file";
  let lastBlob = null;       // the exact file we sent, so "Download annexure" checks the same draft
  let lastName = "draft";
  let lastReports = [];

  /* ---------- top bar shadow on scroll ---------- */
  const topbar = $(".topbar");
  const onScroll = () => topbar.classList.toggle("is-scrolled", window.scrollY > 8);
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---------- tabs ---------- */
  function selectTab(tab) {
    tabs.forEach((t) => {
      const on = t === tab;
      t.classList.toggle("is-active", on);
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      panels[t.id].hidden = !on;
    });
    mode = tab.id === "tab-text" ? "text" : "file";
    hideError();
  }
  tabs.forEach((t) => {
    t.addEventListener("click", () => selectTab(t));
    t.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        const next = tabs[(tabs.indexOf(t) + 1) % tabs.length];
        selectTab(next);
        next.focus();
      }
    });
  });

  /* ---------- file picking and drag and drop ---------- */
  function showFile(file) {
    if (!file) return;
    drop.classList.add("has-file");
    $("#drop-title").textContent = file.name;
    $("#drop-hint").textContent = `${(file.size / 1024).toFixed(file.size < 10240 ? 1 : 0)} KB · ready to check`;
    hideError();
  }
  fileInput.addEventListener("change", () => showFile(fileInput.files[0]));
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault();
    drop.classList.add("is-over");
  }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault();
    drop.classList.remove("is-over");
  }));
  drop.addEventListener("drop", (e) => {
    const file = e.dataTransfer && e.dataTransfer.files[0];
    if (!file) return;
    const dt = new DataTransfer();
    dt.items.add(file);
    fileInput.files = dt.files;
    showFile(file);
  });

  /* ---------- sample ---------- */
  $("#sample-btn").addEventListener("click", () => {
    selectTab(tabs[1]);
    textInput.value = SAMPLE;
    submit("Sample draft");
  });

  /* ---------- submit ---------- */
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    submit();
  });
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      submit();
    }
  });

  function currentDraft() {
    if (mode === "text") {
      const text = textInput.value.trim();
      if (!text) return null;
      return { blob: new File([text], "pasted-draft.txt", { type: "text/plain" }), name: "Pasted text" };
    }
    const file = fileInput.files[0];
    return file ? { blob: file, name: file.name } : null;
  }

  function formFor(blob, name) {
    const data = new FormData();
    data.append("draft", blob, blob.name || name);
    const llm = form.querySelector('input[name="use_llm"]');
    if (llm && llm.checked) data.append("use_llm", "true");
    return data;
  }

  async function readError(res) {
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") return body.detail;
    } catch (_) { /* not JSON */ }
    if (res.status === 429) return "Too many checks in a minute. Wait a moment and try again.";
    return `The check failed (error ${res.status}). Please try again.`;
  }

  async function submit(label) {
    const draft = currentDraft();
    if (!draft) {
      showError(mode === "text" ? "Paste some text first." : "Choose or drop a file first.");
      return;
    }
    setBusy(true);
    hideError();
    try {
      const res = await fetch("/check", { method: "POST", body: formFor(draft.blob, draft.name) });
      if (!res.ok) throw new Error(await readError(res));
      const body = await res.json();
      lastBlob = draft.blob;
      lastName = label || draft.name;
      render(body, lastName);
    } catch (err) {
      showError(err.message && !/fetch/i.test(err.message) ? err.message
        : "Could not reach the server. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  function setBusy(on) {
    checkBtn.disabled = on;
    const lbl = $(".btn__label", checkBtn);
    const existing = $(".spinner", checkBtn);
    if (on && !existing) checkBtn.prepend(el("span", "spinner"));
    if (!on && existing) existing.remove();
    lbl.textContent = on ? "Checking against the judgments…" : "Check citations";
  }
  function showError(msg) { errorBox.textContent = msg; errorBox.hidden = false; }
  function hideError() { errorBox.hidden = true; }

  /* ---------- rendering ---------- */
  const SMALL = new Set(["of", "and", "the", "in", "for", "to", "on", "at", "by", "with", "&", "v."]);
  const ACRONYMS = new Set(["UOI", "DDA", "CBI", "LIC", "ONGC", "BSNL", "MTNL", "SBI", "RBI", "UPSC",
    "NHAI", "CIT", "ESI", "UP", "MP", "HP", "NCT", "NDMC", "MCD", "BHEL", "SAIL", "GAIL", "IOC",
    "BPCL", "HPCL", "NTPC", "KSEB", "TNEB", "CWT", "ITO", "CCE", "CST", "ED", "NIA", "SEBI", "CCI",
    "DLF", "HUF", "IAS", "IPS", "UGC", "AICTE", "ICAI", "NOIDA", "BMC", "LRS", "LR", "PVT", "II", "III", "IV"]);
  function prettyTitle(title) {
    if (!title) return "";
    const t = title.replace(/\s+/g, " ").replace(/\bversus\b/i, "v.").trim();
    if (t.replace(/\bv\.\s/, "") !== t.replace(/\bv\.\s/, "").toUpperCase()) return t; // already mixed case
    const words = t.split(" ");
    return words.map((w, i) => {
      const lw = w.toLowerCase();
      if (i > 0 && SMALL.has(lw) && words[i - 1] !== "v.") return lw;
      if (/^([A-Z]\.){1,4}[A-Z]?\.?,?$/.test(w)) return w;        // U.P., C.B.I.
      if (ACRONYMS.has(w.replace(/[^A-Z]/g, ""))) return w;         // UOI, DDA, ONGC
      return lw.replace(/(^|[(\-/'])([a-z])/g, (_, p, c) => p + c.toUpperCase());
    }).join(" ");
  }

  function methodText(r) {
    const res = r.resolution || {};
    switch (res.method) {
      case "neutral": return "Proven by its neutral citation";
      case "reporter": return "Proven by its SCR citation";
      case "alias": {
        const n = res.witnesses || 0;
        return n >= 2 ? `Proven: ${n} other judgments print this citation for this case`
          : `Only ${n} other judgment prints this citation for this case (not proven)`;
      }
      case "fuzzy": return "Matched on the party names only (not proven)";
      case "ambiguous": return "The number belongs to more than one judgment";
      default: return "";
    }
  }

  // Word-level comparison: words of the draft that the judgment lacks are struck, and words of
  // the judgment the draft lacks are highlighted. Longest common subsequence on normalised words.
  const norm = (w) => w.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
  function diffWords(a, b) {
    const A = a.split(/\s+/).filter(Boolean).slice(0, 400);
    const B = b.split(/\s+/).filter(Boolean).slice(0, 400);
    const n = A.length, m = B.length;
    const L = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        L[i][j] = norm(A[i]) === norm(B[j]) ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
      }
    }
    const keepA = new Array(n).fill(false), keepB = new Array(m).fill(false);
    let i = 0, j = 0;
    while (i < n && j < m) {
      if (norm(A[i]) === norm(B[j])) { keepA[i] = keepB[j] = true; i++; j++; }
      else if (L[i + 1][j] >= L[i][j + 1]) i++;
      else j++;
    }
    return { A, B, keepA, keepB };
  }
  function fillWords(node, words, keep, markClass) {
    node.textContent = "";
    words.forEach((w, k) => {
      if (k) node.append(" ");
      if (keep[k] || !norm(w)) node.append(w);
      else node.append(el("mark", markClass, w));
    });
  }

  function fact(dl, label, value) {
    if (!value) return;
    const row = el("div");
    row.append(el("dt", null, label), el("dd", null, value));
    dl.append(row);
  }

  function card(r, index) {
    const node = $("#card-tpl").content.firstElementChild.cloneNode(true);
    const [kind, label] = STATUS[r.status] || ["none", r.status];
    node.classList.add(`s-${kind}`);
    node.dataset.status = r.status;
    node.style.animationDelay = `${Math.min(index, 12) * 45}ms`;
    $(".cit__no", node).textContent = String(index + 1).padStart(2, "0");
    const chip = $(".chip", node);
    chip.textContent = label;
    chip.classList.add(`chip--${kind}`);
    $(".cit__code", node).textContent = r.status;
    $(".cit__name", node).textContent = r.case_name || prettyTitle(r.case_title) || r.raw;
    $(".cit__raw", node).textContent = r.raw;
    $(".cit__reason", node).textContent = r.reason;

    const dl = $(".cit__facts", node);
    if (r.case_title) fact(dl, "Judgment", `${prettyTitle(r.case_title)}${r.case_year ? ` (${r.case_year})` : ""}`);
    fact(dl, "Found by", methodText(r));
    if (r.paragraph && r.paragraph.status !== "cannot_check" && r.paragraph.explanation) {
      fact(dl, "Paragraph", r.paragraph.explanation);
    }
    if (!dl.children.length) dl.remove();

    const q = r.quote;
    if (r.draft_quote && q && q.status !== "too_short") {
      const box = $(".cit__quote", node);
      box.hidden = false;
      const draftText = $(".q--draft .q__text", node);
      const judgLabel = $(".q--judgment .q__label", node);
      const judgText = $(".q--judgment .q__text", node);
      const original = q.matched_original || "";
      if ((q.status === "verbatim" || q.status === "near_match") && original) {
        const para = q.para_nos && q.para_nos.length && q.para_nos[0] > 0 ? `, para ${q.para_nos[0]}` : "";
        judgLabel.textContent = `The judgment says${para}`;
        const d = diffWords(r.draft_quote, original);
        fillWords(draftText, d.A, d.keepA, "del");
        fillWords(judgText, d.B, d.keepB, "add");
      } else {
        draftText.textContent = r.draft_quote;
        judgLabel.textContent = "The judgment";
        judgText.textContent = "These words were not found in the judgment.";
        judgText.style.fontStyle = "italic";
        judgText.style.color = "var(--muted)";
      }
      if (q.changes && q.changes.length) {
        const ul = $(".cit__changes", node);
        ul.hidden = false;
        q.changes.slice(0, 6).forEach((c) => ul.append(el("li", null, c.charAt(0).toUpperCase() + c.slice(1))));
      }
    }
    return node;
  }

  function counts(reports) {
    const c = {};
    reports.forEach((r) => { c[r.status] = (c[r.status] || 0) + 1; });
    return c;
  }

  function headline(reports, c) {
    const n = reports.length;
    if (!n) return "No citations found in this draft";
    const ok = c.VERIFIED || 0;
    const bad = reports.filter((r) => (STATUS[r.status] || [])[0] === "bad").length;
    let s = `${ok} of ${n} citation${n === 1 ? "" : "s"} verified`;
    if (bad) s += ` · ${bad} flagged`;
    return s;
  }

  function render(body, sourceLabel) {
    const reports = body.citations || [];
    lastReports = reports;
    const c = counts(reports);
    $("#results-source").textContent = `${sourceLabel} · ${body.date || ""}`;
    $("#results-title").textContent = headline(reports, c);
    $("#disclaimer").textContent = body.disclaimer || "";

    const meter = $("#meter");
    meter.textContent = "";
    ORDER.filter((s) => c[s]).forEach((s) => {
      const seg = el("span");
      seg.style.flex = String(c[s]);
      seg.style.background = `var(${COLOUR[(STATUS[s] || ["none"])[0]]})`;
      meter.append(seg);
    });
    meter.hidden = !reports.length;

    const filters = $("#filters");
    filters.textContent = "";
    const all = filterBtn("All", reports.length, null);
    all.setAttribute("aria-pressed", "true");
    filters.append(all);
    ORDER.filter((s) => c[s]).forEach((s) => filters.append(filterBtn((STATUS[s] || [])[1] || s, c[s], s)));
    filters.hidden = reports.length < 2;

    const list = $("#cards");
    list.textContent = "";
    if (!reports.length) {
      const empty = el("li", "card cit s-none");
      const bodyDiv = el("div", "cit__body");
      bodyDiv.append(
        el("h3", "cit__name", "Nothing to check"),
        el("p", "cit__reason", "We look for citations such as 2023 INSC 11, [1973] 1 S.C.R. 1, (2019) 7 SCC 42 or AIR 1960 SC 137. Short forms such as “supra” are not checked."),
      );
      empty.append(el("div", "cit__rail"), bodyDiv);
      list.append(empty);
    }
    reports.forEach((r, i) => list.append(card(r, i)));

    $("#download-btn").hidden = !reports.length;
    $("#copy-btn").hidden = !reports.length;
    results.hidden = false;
    results.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    $("#results-title").focus({ preventScroll: true });
  }

  function filterBtn(label, n, status) {
    const b = el("button", "filter");
    b.type = "button";
    b.setAttribute("aria-pressed", "false");
    if (status) {
      const dot = el("i");
      dot.style.background = `var(${COLOUR[(STATUS[status] || ["none"])[0]]})`;
      b.append(dot);
    }
    b.append(document.createTextNode(label + " "), el("b", null, String(n)));
    b.addEventListener("click", () => {
      document.querySelectorAll(".filter").forEach((f) => f.setAttribute("aria-pressed", String(f === b)));
      document.querySelectorAll("#cards .cit").forEach((cardNode) => {
        cardNode.hidden = status ? cardNode.dataset.status !== status : false;
      });
    });
    return b;
  }

  /* ---------- result actions ---------- */
  $("#copy-btn").addEventListener("click", async (e) => {
    const lines = lastReports.map((r, i) => `${i + 1}. [${r.status}] ${r.raw}${r.case_name ? ` (${r.case_name})` : ""}\n   ${r.reason}`);
    lines.push("", "Checked with Pramaan. Automated check, not legal advice.");
    const btn = e.currentTarget;
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      flash(btn, "Copied");
    } catch (_) {
      flash(btn, "Copy not allowed here");
    }
  });

  $("#download-btn").addEventListener("click", async (e) => {
    if (!lastBlob) return;
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const res = await fetch("/report", { method: "POST", body: formFor(lastBlob, lastName) });
      if (!res.ok) throw new Error(await readError(res));
      const html = await res.blob();
      const a = el("a");
      a.href = URL.createObjectURL(html);
      a.download = `pramaan-annexure-${new Date().toISOString().slice(0, 10)}.html`;
      document.body.append(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
      flash(btn, "Downloaded");
    } catch (err) {
      flash(btn, "Download failed");
      showError(err.message);
    } finally {
      btn.disabled = false;
    }
  });

  $("#reset-btn").addEventListener("click", () => {
    results.hidden = true;
    form.reset();
    drop.classList.remove("has-file");
    $("#drop-title").textContent = "Drop your draft here";
    $("#drop-hint").textContent = $("#drop-hint").dataset.initial || $("#drop-hint").textContent;
    $("#checker").scrollIntoView({ behavior: "smooth", block: "center" });
  });
  $("#drop-hint").dataset.initial = $("#drop-hint").textContent;

  function flash(btn, text) {
    const original = btn.dataset.label || btn.innerHTML;
    btn.dataset.label = original;
    btn.textContent = text;
    setTimeout(() => { btn.innerHTML = original; }, 1600);
  }

  /* ---------- /?sample runs the sample at once (a link to show someone) ---------- */
  if (new URLSearchParams(location.search).has("sample")) $("#sample-btn").click();

})();
