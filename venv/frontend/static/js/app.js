"use strict";

// ── Fine rates (must match challan.py) ─────────────────────────────────────
const FINE_RATES = {
  "Helmet Violation": 1000,
  "Triple Riding":    2000,
  "Mobile Usage":     1500,
};

const VIOLATION_META = {
  "Helmet Violation": { icon: "🪖", cls: "badge-helmet", pillCls: "pill-helmet", dotCls: "helmet", label: "Helmet Violations" },
  "Triple Riding":    { icon: "👥", cls: "badge-triple", pillCls: "pill-triple", dotCls: "triple", label: "Triple Riding"      },
  "Mobile Usage":     { icon: "📱", cls: "badge-mobile", pillCls: "pill-mobile", dotCls: "mobile", label: "Mobile Usage"       },
};


// ── Particle Background ─────────────────────────────────────────────────────
(function () {
  const canvas = document.getElementById("bgCanvas");
  const ctx = canvas.getContext("2d");
  let W, H, pts = [];

  const resize = () => { W = canvas.width = innerWidth; H = canvas.height = innerHeight; };
  const rand = (min, max) => Math.random() * (max - min) + min;

  function init() {
    resize();
    pts = Array.from({ length: 110 }, () => ({
      x: rand(0, W), y: rand(0, H),
      r: rand(0.3, 1.5),
      dx: rand(-0.25, 0.25), dy: rand(-0.25, 0.25),
      alpha: rand(0.08, 0.35),
      color: Math.random() > 0.6 ? '139,92,246' : '59,130,246',
    }));
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    // Draw connections
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y;
        const dist = Math.sqrt(dx*dx + dy*dy);
        if (dist < 130) {
          ctx.strokeStyle = `rgba(59,130,246,${0.04 * (1 - dist/130)})`;
          ctx.lineWidth = 0.5;
          ctx.beginPath(); ctx.moveTo(pts[i].x, pts[i].y); ctx.lineTo(pts[j].x, pts[j].y); ctx.stroke();
        }
      }
    }
    // Draw dots
    for (const p of pts) {
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI*2);
      ctx.fillStyle = `rgba(${p.color},${p.alpha})`; ctx.fill();
      p.x += p.dx; p.y += p.dy;
      if (p.x < 0 || p.x > W) p.dx *= -1;
      if (p.y < 0 || p.y > H) p.dy *= -1;
    }
    requestAnimationFrame(draw);
  }

  window.addEventListener("resize", init);
  init(); draw();
})();


// ── GSAP Hero entrance ──────────────────────────────────────────────────────
window.addEventListener("load", () => {
  if (typeof gsap !== "undefined") {
    const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
    tl.from(".hero-tag",     { y: 20, opacity: 0, duration: 0.6 })
      .from(".hero h1",      { y: 30, opacity: 0, duration: 0.7 }, "-=0.3")
      .from(".hero-sub",     { y: 20, opacity: 0, duration: 0.6 }, "-=0.4")
      .from(".hero-cta",     { y: 20, opacity: 0, duration: 0.5 }, "-=0.3")
      .from(".hero-stats",   { y: 15, opacity: 0, duration: 0.5 }, "-=0.2")
      .from(".hero-graphic", { scale: 0.8, opacity: 0, duration: 0.8, ease: "back.out(1.5)" }, "-=0.7");
  }

  // Step cards: use IntersectionObserver so they always complete animation
  const stepCards = document.querySelectorAll(".step-card");
  const stepObs = new IntersectionObserver((entries) => {
    entries.forEach((entry, _) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("step-visible");
        stepObs.unobserve(entry.target);
      }
    });
  }, { threshold: 0.15 });
  stepCards.forEach((card, i) => {
    card.style.transitionDelay = (i * 0.1) + "s";
    stepObs.observe(card);
  });
});


// ── DOM refs ────────────────────────────────────────────────────────────────
const dropZone        = document.getElementById("dropZone");
const fileInput       = document.getElementById("fileInput");
const filePreview     = document.getElementById("filePreview");
const previewIcon     = document.getElementById("previewIcon");
const previewName     = document.getElementById("previewName");
const previewSize     = document.getElementById("previewSize");
const clearFileBtn    = document.getElementById("clearFile");
const detectBtn       = document.getElementById("detectBtn");
const progressSection = document.getElementById("progressSection");
const progressBar     = document.getElementById("progressBar");
const progressPct     = document.getElementById("progressPct");
const progressTitle   = document.getElementById("progressTitle");
const progressSub     = document.getElementById("progressSub");
const resultsSection  = document.getElementById("results-section");
const summaryBar      = document.getElementById("summaryBar");
const violationsGrid  = document.getElementById("violationsGrid");
const noViolations    = document.getElementById("noViolations");
const challanSection  = document.getElementById("challanSection");
const challanId       = document.getElementById("challanId");
const totalFine       = document.getElementById("totalFine");
const grandBreakdown  = document.getElementById("grandBreakdown");
const downloadBtn     = document.getElementById("downloadBtn");
const tryAgainBtn     = document.getElementById("tryAgainBtn");
const lightbox        = document.getElementById("lightbox");
const lightboxImg     = document.getElementById("lightboxImg");
const lightboxClose   = document.getElementById("lightboxClose");
const lightboxPlate   = document.getElementById("lightboxPlate");
const lightboxTypes   = document.getElementById("lightboxTypes");

let selectedFile = null, currentJobId = null, pollInterval = null;


// ── Lightbox ─────────────────────────────────────────────────────────────────
function openLightbox(src, plate, types) {
  lightboxImg.src = src;
  lightboxPlate.textContent = plate || "—";
  lightboxTypes.textContent = types.join("  |  ");
  lightbox.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  // CSS @keyframes lightboxIn handles the animation — no GSAP needed here
}
function closeLightbox() { lightbox.classList.add("hidden"); document.body.style.overflow = ""; }
lightboxClose.addEventListener("click", closeLightbox);
lightbox.addEventListener("click", e => { if (e.target === lightbox || e.target.classList.contains("lightbox-backdrop")) closeLightbox(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeLightbox(); });


// ── File helpers ──────────────────────────────────────────────────────────────
function fmt(b) {
  return b < 1024 ? b+" B" : b < 1024*1024 ? (b/1024).toFixed(1)+" KB" : (b/1e6).toFixed(2)+" MB";
}
function showPreview(file) {
  selectedFile = file;
  previewIcon.textContent = file.type.startsWith("video") ? "🎬" : "🖼️";
  previewName.textContent = file.name;
  previewSize.textContent = fmt(file.size);
  filePreview.classList.remove("hidden");
  if (typeof gsap !== "undefined") gsap.from("#filePreview", { y:10, opacity:0, duration:0.35, ease:"power2.out" });
}
function clearFile() { selectedFile = null; fileInput.value = ""; filePreview.classList.add("hidden"); }

// Upload click — avoid double-trigger from label
dropZone.addEventListener("click", e => {
  if (!e.target.closest("label") && !e.target.closest("button")) fileInput.click();
});
dropZone.addEventListener("dragover",  e => { e.preventDefault(); dropZone.classList.add("drag-over"); });
dropZone.addEventListener("dragleave", ()  => dropZone.classList.remove("drag-over"));
dropZone.addEventListener("drop", e => {
  e.preventDefault(); dropZone.classList.remove("drag-over");
  if (e.dataTransfer.files[0]) showPreview(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => { if (fileInput.files[0]) showPreview(fileInput.files[0]); });
clearFileBtn.addEventListener("click", clearFile);


// ── Detection ─────────────────────────────────────────────────────────────────
detectBtn.addEventListener("click", startDetection);

async function startDetection() {
  if (!selectedFile) return;
  resultsSection.classList.add("hidden");
  progressSection.classList.remove("hidden");
  detectBtn.disabled = true;
  updateProgress(0, "Uploading file…", "Sending to server");

  const form = new FormData();
  form.append("file", selectedFile);
  let res, data;
  try { res = await fetch("/upload", { method:"POST", body:form }); data = await res.json(); }
  catch(err) { showError("Upload failed: " + err.message); return; }
  if (!res.ok || data.error) { showError(data.error || "Upload failed"); return; }
  currentJobId = data.job_id;
  startPolling();
}


// ── Progress ──────────────────────────────────────────────────────────────────
const STEPS = ["step1","step2","step3","step4","step5"];
function setStepsUpTo(idx) {
  STEPS.forEach((id,i) => {
    const el = document.getElementById(id);
    el.className = i < idx ? "chip done" : i === idx ? "chip active" : "chip";
  });
}
function updateProgress(pct, title, sub) {
  progressBar.style.width = pct + "%";
  progressPct.textContent = pct + "%";
  if (title) progressTitle.textContent = title;
  if (sub)   progressSub.textContent   = sub;
  setStepsUpTo(pct < 20 ? 0 : pct < 40 ? 1 : pct < 60 ? 2 : pct < 80 ? 3 : pct < 100 ? 4 : 5);
}


// ── Polling ───────────────────────────────────────────────────────────────────
function startPolling() {
  pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`/status/${currentJobId}`);
      const data = await res.json();
      if (data.status === "queued")      updateProgress(5,  "Queued…", "Waiting for slot");
      else if (data.status === "processing") updateProgress(data.progress||10, "Analysing…", "Running models");
      else if (data.status === "done")   { clearInterval(pollInterval); updateProgress(100, "Complete!", "Done"); setTimeout(() => showResults(data), 700); }
      else if (data.status === "error")  { clearInterval(pollInterval); showError(data.error||"Error"); }
    } catch(_){}
  }, 1200);
}


// ── Results ───────────────────────────────────────────────────────────────────
function calcFine(vtypes) {
  return vtypes.reduce((s, t) => s + (FINE_RATES[t] || 0), 0);
}

function showResults(data) {
  progressSection.classList.add("hidden");
  resultsSection.classList.remove("hidden");
  resultsSection.scrollIntoView({ behavior:"smooth", block:"start" });

  const violations = data.violations || [];
  const typeSummary= data.type_summary || {};
  const challan    = data.challan;

  // Summary pills
  summaryBar.innerHTML = "";
  const tp = document.createElement("div");
  tp.className = "summary-pill pill-total";
  tp.innerHTML = `✅ <strong>${violations.length}</strong>&nbsp;Motorcycle${violations.length!==1?"s":""} Violated`;
  summaryBar.appendChild(tp);
  for (const [vt, cnt] of Object.entries(typeSummary)) {
    const meta = VIOLATION_META[vt] || { icon:"⚠️", pillCls:"pill-mobile", label:vt };
    const pl = document.createElement("div");
    pl.className = `summary-pill ${meta.pillCls}`;
    pl.innerHTML = `${meta.icon} <strong>${cnt}</strong>&nbsp;${meta.label}`;
    summaryBar.appendChild(pl);
  }
  if (typeof gsap !== "undefined") gsap.from(".summary-pill", { x:-20, opacity:0, duration:0.4, stagger:0.08, ease:"power2.out" });

  violationsGrid.innerHTML = "";

  if (!violations.length) {
    noViolations.classList.remove("hidden");
    
    // Display appropriate message based on whether motorcycles were detected
    const noViolationsTitle = document.getElementById("noViolationsTitle");
    const noViolationsMessage = document.getElementById("noViolationsMessage");
    
    if (!data.motorcycles_detected) {
      noViolationsTitle.textContent = "no motorcycle detected";
      noViolationsMessage.textContent = "No motorcycle detected in this image/video.";
    } else {
      noViolationsTitle.textContent = "No Violations Detected";
      noViolationsMessage.textContent = "All riders appear to be complying with traffic rules.";
    }
    
    challanSection.classList.add("hidden");
  } else {
    noViolations.classList.add("hidden");
    const sorted = [...violations].sort((a,b) => b.confidence - a.confidence);
    sorted.forEach((v, i) => {
      const card = buildVioCard(v, i);
      violationsGrid.appendChild(card);
    });
    if (typeof gsap !== "undefined") gsap.from(".vio-card", { y:40, opacity:0, scale:0.95, duration:0.55, stagger:0.1, ease:"back.out(1.3)" });

    if (challan) {
      challanSection.classList.remove("hidden");
      challanId.textContent = "ID: " + challan.challan_id;

      // Animate grand total counter
      if (typeof gsap !== "undefined") {
        gsap.to({val:0}, { val: challan.total_fines, duration:1.2, ease:"power2.out",
          onUpdate: function() { totalFine.textContent = "₹" + Math.round(this.targets()[0].val).toLocaleString("en-IN"); }
        });
      } else { totalFine.textContent = "₹" + challan.total_fines.toLocaleString("en-IN"); }

      // Build grand breakdown table
      buildGrandBreakdown(violations, challan);
      downloadBtn.onclick = () => window.location = `/download_challan/${currentJobId}`;
    } else {
      challanSection.classList.add("hidden");
    }
  }
  detectBtn.disabled = false;
}


// ── Build grand fine breakdown ────────────────────────────────────────────────
function buildGrandBreakdown(violations, challan) {
  // Collect type counts and total fines
  const typeTotals = {};
  for (const v of violations) {
    for (const vt of v.violation_types) {
      if (!typeTotals[vt]) typeTotals[vt] = { count:0, fine:0 };
      typeTotals[vt].count++;
      typeTotals[vt].fine += FINE_RATES[vt] || 0;
    }
  }

  grandBreakdown.innerHTML = `<div class="grand-breakdown-title">Fine Breakdown</div>`;
  let runningTotal = 0;

  for (const [vt, info] of Object.entries(typeTotals)) {
    const meta = VIOLATION_META[vt] || { icon:"⚠️", dotCls:"mobile" };
    runningTotal += info.fine;
    const row = document.createElement("div");
    row.className = "grand-row";
    row.innerHTML = `
      <span class="grand-row-type">
        <span class="fine-dot ${meta.dotCls}"></span>
        ${meta.icon} ${vt}
        <span class="grand-row-count">×${info.count}</span>
      </span>
      <span class="grand-row-amount">₹${info.fine.toLocaleString("en-IN")}</span>`;
    grandBreakdown.appendChild(row);
  }

  // Total row
  const totRow = document.createElement("div");
  totRow.className = "grand-total-row";
  totRow.innerHTML = `<span class="grand-total-label">🧾 TOTAL</span><span class="grand-total-amt">₹${challan.total_fines.toLocaleString("en-IN")}</span>`;
  grandBreakdown.appendChild(totRow);
}


// ── Build violation card ──────────────────────────────────────────────────────
function buildVioCard(v, idx) {
  const div = document.createElement("div");
  div.className = "vio-card";
  div.style.animationDelay = (idx * 0.07) + "s";

  const badges = v.violation_types.map(vt => {
    const meta = VIOLATION_META[vt] || { icon:"⚠️", cls:"badge-mobile" };
    return `<span class="vio-badge ${meta.cls}">${meta.icon} ${vt}</span>`;
  }).join("");

  const imgSrc     = "/" + v.crop_path.replace(/\\/g,"/");
  const frameLabel = v.frame_id > 0 ? `Frame ${v.frame_id}` : "Image";
  const plateHtml  = v.license_plate
    ? `<div class="vio-plate-label">License Plate</div><div class="vio-plate-text">${v.license_plate}</div>`
    : `<div class="vio-plate-label">License Plate</div><div class="plate-none">Not extracted</div>`;

  // Per-card fine breakdown
  const fineRows = v.violation_types.map(vt => {
    const meta = VIOLATION_META[vt] || { icon:"⚠️", dotCls:"mobile" };
    const amt  = FINE_RATES[vt] || 0;
    return `<div class="fine-row">
      <span class="fine-type"><span class="fine-dot ${meta.dotCls}"></span>${meta.icon} ${vt}</span>
      <span class="fine-amount-row">₹${amt.toLocaleString("en-IN")}</span>
    </div>`;
  }).join("");

  const cardTotal = calcFine(v.violation_types);
  const totalHtml = `<div class="fine-divider"></div>
    <div class="fine-total-row">
      <span class="fine-total-label">Total Fine</span>
      <span class="fine-total-amount">₹${cardTotal.toLocaleString("en-IN")}</span>
    </div>`;

  div.innerHTML = `
    <div class="vio-img-wrap">
      <img class="vio-img" src="${imgSrc}" alt="Violation" loading="lazy"
           onerror="this.parentElement.innerHTML='<div style=padding:20px;text-align:center;color:#475569>No preview</div>'"/>
      <div class="vio-badges">${badges}</div>
      <div class="expand-hint">🔍 Click to expand</div>
    </div>
    <div class="vio-body">
      <div class="vio-plate">
        <span class="plate-icon">🔤</span>
        <div>${plateHtml}</div>
      </div>
      <div class="fine-breakdown">
        ${fineRows}
        ${totalHtml}
      </div>
      <div class="vio-meta">
        <span class="vio-conf">Conf: ${(v.confidence*100).toFixed(1)}%</span>
        <span class="vio-frame">${frameLabel}</span>
      </div>
    </div>`;

  div.querySelector(".vio-img-wrap").addEventListener("click", () =>
    openLightbox(imgSrc, v.license_plate, v.violation_types));

  return div;
}


// ── Error ─────────────────────────────────────────────────────────────────────
function showError(msg) { progressSection.classList.add("hidden"); detectBtn.disabled = false; alert("❌ "+msg); }


// ── Try Again ─────────────────────────────────────────────────────────────────
tryAgainBtn.addEventListener("click", () => {
  resultsSection.classList.add("hidden");
  progressSection.classList.add("hidden");
  clearFile(); currentJobId = null;
  document.getElementById("upload-section").scrollIntoView({ behavior:"smooth" });
});
