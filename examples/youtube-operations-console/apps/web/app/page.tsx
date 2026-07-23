"use client";

import { useMemo, useState } from "react";

const copy = {
  en: {
    eyebrow: "Live operations",
    title: "Your channels, under control.",
    subtitle: "Monitoring runs continuously. Every write waits for one account, one review, one explicit approval.",
    pending: "Pending approvals",
    review: "Review proposal",
  },
  tr: {
    eyebrow: "Canlı operasyon",
    title: "Kanallarınız, kontrol altında.",
    subtitle: "İzleme sürekli çalışır. Her yazma işlemi tek hesap, tek inceleme ve açık onay bekler.",
    pending: "Bekleyen onaylar",
    review: "Teklifi incele",
  },
};

const nav = ["Overview", "Accounts", "Monitoring", "Approval center", "Audit log"];

const proposals = [
  {
    id: "ACT-2841",
    account: "Field Notes",
    target: "Designing calm interfaces",
    action: "Comment draft",
    agent: "agy-youtube-compliance",
    risk: "Low",
    draft: "The way you connect pacing with information hierarchy is especially useful. The quiet moments make the key ideas land.",
    quota: "50 units",
  },
  {
    id: "ACT-2839",
    account: "Studio North",
    target: "Systems for creative teams",
    action: "Like proposal",
    agent: "glm-orchestrator",
    risk: "Low",
    draft: "Like this video from the selected Studio North account.",
    quota: "1 unit",
  },
];

function SignalMark() {
  return <span className="signal-mark" aria-hidden="true"><i /><i /><i /></span>;
}

export default function Home() {
  const [active, setActive] = useState("Overview");
  const [locale, setLocale] = useState<"en" | "tr">("en");
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [selected, setSelected] = useState<(typeof proposals)[number] | null>(null);
  const [approved, setApproved] = useState<string[]>([]);
  const t = copy[locale];
  const reviewed = useMemo(() => proposals.filter((proposal) => approved.includes(proposal.id)), [approved]);

  return (
    <main className="console" data-theme={theme}>
      <aside className="sidebar" aria-label="Primary navigation">
        <div className="brand"><SignalMark /><span>SIGNAL</span></div>
        <div className="workspace">
          <span className="workspace-avatar">SN</span>
          <span><b>Studio Network</b><small>Operations workspace</small></span>
          <button aria-label="Switch workspace">⌄</button>
        </div>
        <nav>
          {nav.map((item, index) => (
            <button key={item} className={active === item ? "active" : ""} onClick={() => setActive(item)}>
              <span aria-hidden="true">{["⌂", "◎", "◌", "✓", "≡"][index]}</span>{item}
              {item === "Approval center" && <em>2</em>}
            </button>
          ))}
        </nav>
        <div className="policy-card">
          <span className="status-dot" /> Policy guard active
          <p>Bulk and background engagement are blocked.</p>
          <a href="#audit">View safety policy</a>
        </div>
        <div className="operator"><span>YK</span><p><b>Yasir Karaman</b><small>Workspace owner</small></p><button aria-label="Open user menu">•••</button></div>
      </aside>

      <section className="main-stage">
        <header className="topbar">
          <div className="command">⌘ <span>Search channels, videos, actions…</span><kbd>⌘ K</kbd></div>
          <div className="top-actions">
            <button className="locale" onClick={() => setLocale(locale === "en" ? "tr" : "en")}>{locale.toUpperCase()}</button>
            <button aria-label="Toggle color theme" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? "☼" : "☾"}</button>
            <button aria-label="Notifications">♢<span className="notification-dot" /></button>
            <button className="connect"><span>＋</span> Connect account</button>
          </div>
        </header>

        <div className="content">
          <div className="hero-heading">
            <div><p className="eyebrow"><span className="live-dot" />{t.eyebrow}</p><h1>{t.title}</h1><p>{t.subtitle}</p></div>
            <div className="range"><button className="selected">24h</button><button>7d</button><button>30d</button></div>
          </div>

          <section className="metric-grid" aria-label="Workspace summary">
            <article><span>Connected accounts</span><strong>04</strong><small><i className="good" /> All healthy</small></article>
            <article><span>Channels monitored</span><strong>18</strong><small>+3 this month</small></article>
            <article><span>Videos detected today</span><strong>07</strong><small>2 in the last hour</small></article>
            <article className="attention"><span>{t.pending}</span><strong>02</strong><small>Oldest · 18 min</small></article>
          </section>

          <section className="operations-grid">
            <article className="panel pulse-panel">
              <div className="panel-head"><div><span>MONITORING PULSE</span><h2>Channel activity</h2></div><span className="live-pill">● Live</span></div>
              <div className="chart" aria-label="Channel event volume in the last 24 hours">
                <div className="axis"><span>20</span><span>10</span><span>0</span></div>
                <div className="chart-field"><div className="area" /><div className="chart-line" /><span className="peak p1" /><span className="peak p2" /><span className="peak p3" /></div>
              </div>
              <div className="chart-labels"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>Now</span></div>
              <div className="pulse-legend"><span><i className="mint" />New videos <b>7</b></span><span><i className="blue" />Metadata changes <b>12</b></span><span><i className="muted" />Webhook retries <b>1</b></span></div>
            </article>

            <article className="panel quota-panel">
              <div className="panel-head"><div><span>DAILY API BUDGET</span><h2>Quota health</h2></div><button>Details ↗</button></div>
              <div className="quota-ring"><div><strong>31%</strong><span>used today</span></div></div>
              <div className="quota-copy"><b>3,140 / 10,000 units</b><span>Resets in 08h 42m</span></div>
              <div className="quota-row"><span>Reads</span><b>2,760</b><i style={{"--fill": "68%"} as React.CSSProperties} /></div>
              <div className="quota-row"><span>Approved writes</span><b>380</b><i style={{"--fill": "22%"} as React.CSSProperties} /></div>
            </article>
          </section>

          <section className="lower-grid">
            <article className="panel approvals">
              <div className="panel-head"><div><span>HUMAN CHECKPOINT</span><h2>{t.pending}</h2></div><button onClick={() => setActive("Approval center")}>View all 02 →</button></div>
              {proposals.map((proposal) => (
                <button className="proposal" key={proposal.id} onClick={() => setSelected(proposal)}>
                  <span className="proposal-icon">✎</span>
                  <span className="proposal-main"><small>{proposal.action.toUpperCase()} · {proposal.id}</small><b>{proposal.target}</b><span>From <strong>{proposal.account}</strong> · prepared by {proposal.agent}</span></span>
                  <span className="risk"><i />{proposal.risk} risk</span><span className="arrow">›</span>
                </button>
              ))}
              {reviewed.length > 0 && <p className="approved-note">{reviewed.length} proposal approved and locked to its reviewed payload.</p>}
            </article>

            <article className="panel accounts">
              <div className="panel-head"><div><span>ACCOUNT HEALTH</span><h2>Connected channels</h2></div><button onClick={() => setActive("Accounts")}>Manage →</button></div>
              {[
                ["FN", "Field Notes", "@fieldnotes", "Read + write", "74%"],
                ["SN", "Studio North", "@studionorth", "Read + write", "42%"],
                ["GC", "Good Company", "@goodcompany", "Read only", "18%"],
              ].map((account) => (
                <div className="account-row" key={account[1]}><span className="account-avatar">{account[0]}</span><p><b>{account[1]}</b><small>{account[2]}</small></p><span className="scope">{account[3]}</span><div className="mini-quota"><i style={{"--fill": account[4]} as React.CSSProperties} /><small>{account[4]}</small></div><span className="health">● Healthy</span></div>
              ))}
            </article>
          </section>

          <section className="panel audit" id="audit">
            <div className="panel-head"><div><span>TAMPER-EVIDENT TRAIL</span><h2>Recent operations</h2></div><button onClick={() => setActive("Audit log")}>Open audit log →</button></div>
            <div className="audit-table">
              <div className="audit-row header"><span>Actor</span><span>Event</span><span>Resource</span><span>Result</span><span>Time</span></div>
              <div className="audit-row"><span><b>agy-backend</b><small>agent</small></span><span>video.detected</span><span>v_8jw2…</span><span className="ok">Recorded</span><span>2 min ago</span></div>
              <div className="audit-row"><span><b>Yasir K.</b><small>operator</small></span><span>proposal.approved</span><span>ACT-2837</span><span className="ok">Succeeded</span><span>11 min ago</span></div>
              <div className="audit-row"><span><b>policy-guard</b><small>system</small></span><span>cross_account_duplicate</span><span>ACT-2832</span><span className="blocked">Blocked</span><span>24 min ago</span></div>
            </div>
          </section>
        </div>
      </section>

      {selected && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setSelected(null)}>
          <section className="review-modal" role="dialog" aria-modal="true" aria-labelledby="review-title">
            <button className="modal-close" aria-label="Close review" onClick={() => setSelected(null)}>×</button>
            <p className="eyebrow">ONE ACCOUNT · ONE ACTION</p><h2 id="review-title">{t.review}</h2>
            <div className="review-meta"><span><small>Account</small><b>{selected.account}</b></span><span><small>Target</small><b>{selected.target}</b></span><span><small>Quota</small><b>{selected.quota}</b></span></div>
            <label>Reviewable payload<textarea defaultValue={selected.draft} /></label>
            <div className="guardrail"><b>Policy guard</b><p>This approval is bound to one selected account and the exact text hash. Any edit after approval requires a new confirmation.</p></div>
            <label className="confirm"><input type="checkbox" id="confirm-action" /> I reviewed this exact action for {selected.account}.</label>
            <div className="modal-actions"><button onClick={() => setSelected(null)}>Reject</button><button className="approve" onClick={() => { const box = document.getElementById("confirm-action") as HTMLInputElement; if (box?.checked) { setApproved([...approved, selected.id]); setSelected(null); } }}>Approve reviewed action</button></div>
          </section>
        </div>
      )}
    </main>
  );
}
