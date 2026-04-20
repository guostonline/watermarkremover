PE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PDF Clean — Admin Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0e0e12;--glass:rgba(255,255,255,0.04);--glass-border:rgba(255,255,255,0.08);
  --glass-hover:rgba(255,255,255,0.07);--text:#f0f0f5;--text-sec:#8a8a9a;
  --accent:#7c5cfc;--accent-lt:#a78bfa;--accent-glow:rgba(124,92,252,0.25);
  --accent-dim:rgba(124,92,252,0.08);--success:#34d399;--success-dim:rgba(52,211,153,0.1);
  --danger:#f87171;--danger-dim:rgba(248,113,113,0.1);--warn:#fbbf24;--warn-dim:rgba(251,191,36,0.1);
  --radius:16px;--radius-sm:10px;--font:'Outfit',system-ui,sans-serif;--mono:'JetBrains Mono',monospace;
}
html{font-size:16px;-webkit-font-smoothing:antialiased}
body{background:var(--bg);color:var(--text);font-family:var(--font);min-height:100vh;line-height:1.5}
.bg-orbs{position:fixed;inset:0;pointer-events:none;z-index:0;overflow:hidden}
.bg-orbs::before{content:'';position:absolute;width:600px;height:600px;top:-180px;left:-120px;background:radial-gradient(circle,rgba(124,92,252,0.1) 0%,transparent 70%);border-radius:50%}
.bg-orbs::after{content:'';position:absolute;width:400px;height:400px;bottom:-80px;right:-60px;background:radial-gradient(circle,rgba(52,211,153,0.06) 0%,transparent 70%);border-radius:50%}
.container{position:relative;z-index:1;max-width:1000px;margin:0 auto;padding:0 20px 40px}
header{padding:32px 0 24px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}
.brand{font-size:1.3rem;font-weight:700;letter-spacing:-0.02em;background:linear-gradient(135deg,var(--text) 40%,var(--accent-lt));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.badge{font-size:0.6rem;font-weight:600;padding:3px 8px;border-radius:6px;background:var(--accent-dim);color:var(--accent-lt);border:1px solid rgba(124,92,252,0.2);letter-spacing:0.04em;text-transform:uppercase;margin-left:8px;vertical-align:middle}
.header-actions{display:flex;gap:8px;align-items:center}
.btn{background:var(--glass);border:1px solid var(--glass-border);color:var(--text-sec);font-family:var(--font);font-size:0.75rem;font-weight:500;padding:6px 14px;border-radius:8px;cursor:pointer;transition:all 0.2s}
.btn:hover{background:var(--glass-hover);color:var(--text);border-color:rgba(255,255,255,0.12)}
.btn-primary{background:linear-gradient(135deg,var(--accent),#6d4fe0);color:#fff;border:none}
.btn-primary:hover{box-shadow:0 4px 16px var(--accent-glow);transform:translateY(-1px)}
.btn-primary:disabled{opacity:0.4;cursor:not-allowed;transform:none;box-shadow:none}

.grid{display:grid;gap:16px;margin-top:20px}
.g2{grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
.g3{grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.g4{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}
.gf{grid-template-columns:1fr}

.card{background:var(--glass);backdrop-filter:blur(40px);-webkit-backdrop-filter:blur(40px);border:1px solid var(--glass-border);border-radius:var(--radius);padding:20px 22px;transition:border-color 0.3s}
.card:hover{border-color:rgba(255,255,255,0.12)}
.card-title{font-size:0.65rem;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:var(--text-sec);margin-bottom:14px;display:flex;align-items:center;gap:6px}
.card-title svg{width:14px;height:14px}
.card-title .right{margin-left:auto;font-size:0.6rem;text-transform:none;letter-spacing:0;color:var(--text-sec);font-weight:400}

.stat{margin-bottom:14px}.stat:last-child{margin-bottom:0}
.stat-label{font-size:0.65rem;color:var(--text-sec);text-transform:uppercase;letter-spacing:0.06em;font-weight:500}
.stat-value{font-size:1.7rem;font-weight:700;letter-spacing:-0.03em;margin-top:2px;line-height:1.1}
.stat-sub{font-size:0.7rem;color:var(--text-sec);margin-top:4px}
.stat-change{font-size:0.65rem;font-weight:500;display:inline-flex;align-items:center;gap:2px}
.stat-change.up{color:var(--success)}.stat-change.down{color:var(--danger)}.stat-change.flat{color:var(--warn)}

.metric-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.metric{text-align:center;padding:10px 6px;background:var(--glass);border-radius:var(--radius-sm);border:1px solid var(--glass-border)}
.metric-val{font-size:1.2rem;font-weight:700;letter-spacing:-0.02em}
.metric-label{font-size:0.6rem;color:var(--text-sec);text-transform:uppercase;letter-spacing:0.06em;margin-top:2px}
.metric-grid.g3{grid-template-columns:1fr 1fr 1fr}
.metric-grid.g4{grid-template-columns:1fr 1fr 1fr 1fr}

.progress-bar-track{height:4px;background:var(--glass-border);border-radius:2px;margin-top:8px;overflow:hidden}
.progress-bar-fill{height:100%;border-radius:2px;transition:width 0.4s}

.table{width:100%;border-collapse:collapse;font-size:0.78rem}
.table th{text-align:left;font-size:0.6rem;text-transform:uppercase;letter-spacing:0.08em;color:var(--text-sec);font-weight:600;padding:10px 10px;border-bottom:1px solid var(--glass-border)}
.table td{padding:8px 10px;border-bottom:1px solid rgba(255,255,255,0.03)}
.table tr:hover td{background:var(--glass-hover)}
.mono{font-family:var(--mono);font-size:0.72rem}
.time{color:var(--text-sec);font-size:0.68rem}
.tag{font-size:0.55rem;font-weight:600;padding:2px 6px;border-radius:4px;letter-spacing:0.04em;display:inline-block}
.tag-success{background:var(--success-dim);color:var(--success);border:1px solid rgba(52,211,153,0.2)}
.tag-danger{background:var(--danger-dim);color:var(--danger);border:1px solid rgba(248,113,113,0.2)}
.tag-warn{background:var(--warn-dim);color:var(--warn);border:1px solid rgba(251,191,36,0.2)}
.tag-neutral{background:var(--accent-dim);color:var(--accent-lt);border:1px solid rgba(124,92,252,0.2)}

.bar-chart{display:flex;align-items:flex-end;gap:4px;height:100px;margin-top:8px}
.bar-col{flex:1;display:flex;flex-direction:column;gap:1px;align-items:stretch;position:relative;cursor:default}
.bar-col:hover .bar-tooltip{opacity:1}
.bar-success{background:linear-gradient(to top,var(--success),#10b981);border-radius:3px 3px 0 0;min-height:2px;transition:height 0.3s}
.bar-error{background:linear-gradient(to top,var(--danger),#ef4444);border-radius:0 0 3px 3px;min-height:2px;transition:height 0.3s}
.bar-labels{display:flex;gap:4px;margin-top:4px}
.bar-labels span{flex:1;text-align:center;font-size:0.5rem;color:var(--text-sec);font-family:var(--mono)}
.bar-tooltip{position:absolute;top:-28px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.8);color:#fff;font-size:0.6rem;padding:3px 6px;border-radius:4px;white-space:nowrap;opacity:0;transition:opacity 0.15s;pointer-events:none;font-family:var(--mono)}

.error-row{display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.03)}
.error-row:last-child{border-bottom:none}
.error-text{font-size:0.72rem;font-family:var(--mono);color:var(--text-sec);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.error-count{font-size:0.8rem;font-weight:700;color:var(--danger);margin-left:12px;flex-shrink:0}

.login-wrapper{min-height:100vh;display:flex;align-items:center;justify-content:center}
.login-card{width:100%;max-width:380px}
.login-card h2{font-size:1.4rem;font-weight:700;margin-bottom:4px}
.login-card p{font-size:0.8rem;color:var(--text-sec);margin-bottom:20px}
.login-card input{width:100%;padding:12px 16px;background:var(--glass);border:1px solid var(--glass-border);border-radius:var(--radius-sm);color:var(--text);font-family:var(--mono);font-size:0.85rem;outline:none;transition:border-color 0.2s}
.login-card input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-dim)}
.login-card button{width:100%;margin-top:12px;padding:12px;background:linear-gradient(135deg,var(--accent),#6d4fe0);color:#fff;border:none;border-radius:var(--radius-sm);font-family:var(--font);font-size:0.85rem;font-weight:600;cursor:pointer;transition:all 0.25s}
.login-card button:hover{box-shadow:0 4px 20px var(--accent-glow);transform:translateY(-1px)}
.login-card .error{color:var(--danger);font-size:0.75rem;margin-top:8px;display:none}
.login-card .error.visible{display:block}
.empty{text-align:center;padding:30px 20px;color:var(--text-sec)}
.empty p{font-size:0.82rem;margin-top:4px}

.funnel-step{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.03)}
.funnel-step:last-child{border-bottom:none}
.funnel-bar-track{flex:1;height:8px;background:var(--glass-border);border-radius:4px;overflow:hidden}
.funnel-bar-fill{height:100%;border-radius:4px;transition:width 0.4s}
.funnel-label{font-size:0.7rem;color:var(--text-sec);min-width:120px}
.funnel-val{font-size:0.75rem;font-weight:600;min-width:50px;text-align:right;font-family:var(--mono)}

@media(max-width:600px){
  .g2,.g4{grid-template-columns:1fr 1fr}
  .g3{grid-template-columns:1fr}
  header{padding:20px 0 16px}
  .stat-value{font-size:1.3rem}
  .metric-grid.g3,.metric-grid.g4{grid-template-columns:1fr 1fr}
}
::selection{background:var(--accent);color:#fff}
</style>
</head>
<body>
<div class="bg-orbs"></div>
<div id="app"></div>
<script>
const API='/api/admin';
const REFRESH_INTERVAL=30000;
const fmtB=b=>{if(!b||b===0)return'0 B';if(b<1024)return b.toFixed(0)+' B';if(b<1048576)return(b/1024).toFixed(1)+' KB';if(b<1073741824)return(b/1048576).toFixed(1)+' MB';return(b/1073741824).toFixed(1)+' GB'};
const fmtRel=iso=>{if(!iso)return'-';const d=new Date(iso),now=new Date(),diff=now-d;if(diff<60000)return'just now';if(diff<3600000)return Math.floor(diff/60000)+'m ago';if(diff<86400000)return Math.floor(diff/3600000)+'h ago';return Math.floor(diff/86400000)+'d ago'};
const fmtDay=d=>{const dt=new Date(d+'T12:00:00Z');return dt.toLocaleDateString('en-US',{month:'short',day:'numeric'})};

let authToken=null;let data=null;

async function apiFetch(endpoint,opts={}){const h={'Content-Type':'application/json',...opts.headers};if(authToken)h['Authorization']='Bearer '+authToken;const r=await fetch(API+endpoint,{...opts,headers});if(r.status===401)return null;return r.json()}

function changeRate(cur,prev){if(!prev||prev===0)return cur>0?{dir:'up',val:cur>0?'+Infinity':'flat'}:{dir:'flat',val:'-'};const r=((cur-prev)/prev*100);return{dir:r>0?'up':r<0?'down':'flat',val:(r>0?'+':'')+r.toFixed(1)+'%'}}

function renderLogin(){document.getElementById('app').innerHTML=`<div class="login-wrapper"><div class="container"><div class="login-card card"><h2>Admin Dashboard</h2><p>PDF Clean analytics & waitlist management</p><input type="password" id="loginPass" placeholder="Enter admin password" autofocus><div class="error" id="loginError">Invalid password</div><button onclick="doLogin()">Sign in</button></div></div></div>`;document.getElementById('loginPass').addEventListener('keydown',e=>{if(e.key==='Enter')doLogin()})}

async function doLogin(){const pass=document.getElementById('loginPass').value;const err=document.getElementById('loginError');err.classList.remove('visible');const r=await fetch(API+'/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pass})});if(!r.ok){err.classList.add('visible');return}const d=await r.json();authToken=d.token;localStorage.setItem('admin_token',authToken);loadData()}

function renderDashboard(){
  if(!data)return;
  const s=data.stats;const wl=data.waitlist||[];const daily=data.daily_chart||[];const events=data.recent_events||[];

  const rate24=changeRate(s.processes_today,s.processes_yesterday);
  const sess24=changeRate(s.sessions_today,s.sessions_yesterday);
  const bytes24=changeRate(s.bytes_today,s.bytes_yesterday);

  const maxDayVal=Math.max(...daily.map(d=>d.success+d.error),1);
  const chartBars=daily.slice().reverse().slice(-14).map(d=>{
    const sH=((d.success||0)/maxDayVal*100).toFixed(0);
    const eH=((d.error||0)/maxDayVal*100).toFixed(0);
    return`<div class="bar-col"><div class="bar-success" style="height:${sH}%"></div><div class="bar-error" style="height:${eH}%"></div><div class="bar-tooltip">${fmtDay(d.date)}: ${d.success||0} ok, ${d.error||0} err</div></div>`;
  }).join('');
  const chartLabels=daily.slice().reverse().slice(-14).map(d=>`<span>${fmtDay(d.date)}</span>`).join('');

  const recentWL=wl.slice(0,20);
  const recentEv=events.slice(0,30);

  const topErrors=(s.top_errors||[]).map(([reason,count])=>`<div class="error-row"><span class="error-text" title="${reason}">${reason}</span><span class="error-count">${count}</span></div>`).join('');

  document.getElementById('app').innerHTML=`
  <div class="container">
    <header>
      <div style="display:flex;align-items:center;gap:8px"><span class="brand">PDF Clean</span><span class="badge">Admin</span></div>
      <div class="header-actions">
        <button class="btn-primary btn" onclick="loadData()" id="refreshBtn">&#x21bb; Refresh</button>
        <button class="btn btn-logout" onclick="logout()">Sign out</button>
      </div>
    </header>

    <div class="grid g4">
      <div class="card">
        <div class="card-title">Waitlist</div>
        <div class="stat"><div class="stat-label">Total signups</div><div class="stat-value">${s.total_waitlist||0}</div></div>
        <div class="metric-grid">
          <div class="metric"><div class="metric-val">${s.processes_today||0}</div><div class="metric-label">Processes today</div></div>
          <div class="metric"><div class="metric-val">${s.sessions_today||0}</div><div class="metric-label">Sessions today</div></div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Processing</div>
        <div class="stat"><div class="stat-label">Total</div><div class="stat-value">${s.total_processes||0}</div></div>
        <div class="metric-grid">
          <div class="metric"><div class="metric-val" style="color:var(--success)">${s.success_processes||0}</div><div class="metric-label">Success</div></div>
          <div class="metric"><div class="metric-val" style="color:var(--danger)">${s.error_processes||0}</div><div class="metric-label">Errors</div></div>
        </div>
        <div class="progress-bar-track"><div class="progress-bar-fill" style="width:${s.success_rate||0}%;background:var(--success)"></div></div>
        <div style="display:flex;justify-content:space-between;margin-top:4px"><span style="font-size:0.65rem;color:var(--text-sec)">Success rate</span><span style="font-size:0.65rem;font-weight:600;color:var(--success);font-family:var(--mono)">${s.success_rate||0}%</span></div>
      </div>

      <div class="card">
        <div class="card-title">Data processed</div>
        <div class="stat"><div class="stat-label">Total</div><div class="stat-value">${s.total_bytes_formatted||'0 B'}</div></div>
        <div class="metric-grid">
          <div class="metric"><div class="metric-val" style="font-size:0.95rem">${s.bytes_today_formatted||'0 B'}</div><div class="metric-label">Today</div></div>
          <div class="metric"><div class="metric-val" style="font-size:0.95rem">${s.bytes_yesterday_formatted||'0 B'}</div><div class="metric-label">Yesterday</div></div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Users</div>
        <div class="stat"><div class="stat-label">Unique sessions</div><div class="stat-value">${s.unique_sessions||0}</div></div>
        <div class="metric-grid">
          <div class="metric"><div class="metric-val">${s.sessions_today||0}</div><div class="metric-label">Today</div></div>
          <div class="metric"><div class="metric-val">${s.sessions_yesterday||0}</div><div class="metric-label">Yesterday</div></div>
        </div>
      </div>
    </div>

    <div class="grid g3" style="margin-top:0">
      <div class="card">
        <div class="card-title">Mode breakdown</div>
        <div class="metric-grid g4">
          <div class="metric"><div class="metric-val">${s.remove_processes||0}</div><div class="metric-label">Remove</div></div>
          <div class="metric"><div class="metric-val">${s.process_processes||0}</div><div class="metric-label">Process</div></div>
          <div class="metric"><div class="metric-val">${s.stamp_processes||0}</div><div class="metric-label">Stamp</div></div>
          <div class="metric"><div class="metric-val">${s.logo_stamps||0}</div><div class="metric-label">Logos</div></div>
        </div>
        <div style="margin-top:14px">
          <div style="display:flex;justify-content:space-between;font-size:0.65rem;color:var(--text-sec)"><span>Logo adoption rate</span><span style="font-family:var(--mono);color:var(--accent-lt)">${s.logo_adoption_rate||0}%</span></div>
          <div class="progress-bar-track"><div class="progress-bar-fill" style="width:${s.logo_adoption_rate||0}%;background:var(--accent)"></div></div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Daily processes <span class="right">${daily.length} days</span></div>
        ${chartBars?`<div class="bar-chart">${chartBars}</div><div class="bar-labels">${chartLabels}</div>`:'<div class="empty"><p>No process data yet</p></div>'}
        <div style="display:flex;gap:12px;margin-top:8px;font-size:0.6rem;color:var(--text-sec)">
          <span><span style="display:inline-block;width:8px;height:8px;background:var(--success);border-radius:2px;vertical-align:middle;margin-right:3px"></span>Success</span>
          <span><span style="display:inline-block;width:8px;height:8px;background:var(--danger);border-radius:0 0 2px 2px;vertical-align:middle;margin-right:3px"></span>Error</span>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Top errors</div>
        ${topErrors||'<div class="empty"><p>No errors recorded</p></div>'}
      </div>
    </div>

    <div class="grid gf" style="margin-top:0">
      <div class="card">
        <div class="card-title">Conversion funnel <span class="right">Waitlist &rarr; Tool &rarr; Process</span></div>
        <div class="funnel-step"><span class="funnel-label">Waitlist signups</span><div class="funnel-bar-track"><div class="funnel-bar-fill" style="width:${wl.length?100:0}%;background:var(--accent)"></div></div><span class="funnel-val">${wl.length}</span></div>
        <div class="funnel-step"><span class="funnel-label">Unique users</span><div class="funnel-bar-track"><div class="funnel-bar-fill" style="width:${wl.length&&s.unique_sessions?((s.unique_sessions/wl.length)*100):0}%;background:var(--accent-lt)"></div></div><span class="funnel-val">${s.unique_sessions||0}</span></div>
        <div class="funnel-step"><span class="funnel-label">Successful processes</span><div class="funnel-bar-track"><div class="funnel-bar-fill" style="width:${s.unique_sessions&&s.success_processes?((s.success_processes/s.unique_sessions)*100):0}%;background:var(--success)"></div></div><span class="funnel-val">${s.success_processes||0}</span></div>
        <div style="margin-top:10px;font-size:0.65rem;color:var(--text-sec)">
          ${wl.length?'Waitlist &rarr; Tool: <strong style="color:var(--accent-lt)">'+(s.unique_sessions?((s.unique_sessions/wl.length)*100).toFixed(1):'0')+'%</strong> &nbsp;|&nbsp; Tool &rarr; Process: <strong style="color:var(--success)">'+(s.unique_sessions&&s.success_processes?((s.success_processes/s.unique_sessions)*100).toFixed(1):'0')+'%</strong>':'No signups yet'}
        </div>
      </div>
    </div>

    <div class="grid g2" style="margin-top:0">
      <div class="card">
        <div class="card-title">Recent signups <span class="right">${wl.length} total</span></div>
        ${recentWL.length===0?'<div class="empty"><p>No signups yet</p></div>':`
        <table class="table"><thead><tr><th>Email</th><th>Joined</th></tr></thead><tbody>${recentWL.map(w=>`<tr><td class="mono">${w.email}</td><td class="time">${fmtRel(w.created_at)}</td></tr>`).join('')}</tbody></table>`}
      </div>

      <div class="card">
        <div class="card-title">Recent activity <span class="right">${events.length} events</span></div>
        ${events.length===0?'<div class="empty"><p>No activity yet</p></div>':`
        <table class="table"><thead><tr><th>Mode</th><th>Status</th><th>Size</th><th>Time</th></tr></thead><tbody>${recentEv.map(e=>`<tr><td><span class="tag ${e.mode==='remove'?'tag-neutral':e.mode==='stamp'?'tag-warn':'tag-success'}">${e.mode}</span></td><td>${e.success?'<span class="tag tag-success">OK</span>':'<span class="tag tag-danger">ERR</span>'}</td><td class="time">${fmtB(e.file_size)}</td><td class="time">${fmtRel(e.ts)}</td></tr>`).join('')}</tbody></table>`}
      </div>
    </div>

    <div class="grid gf" style="margin-top:0">
      <div class="card" style="text-align:center;padding:16px">
        <span style="font-size:0.7rem;color:var(--text-sec)">PostHog</span>
        <div style="margin-top:6px"><a href="https://us.posthog.com" target="_blank" style="color:var(--accent-lt);font-size:0.8rem;font-weight:500;text-decoration:none;border-bottom:1px dashed var(--accent-lt)">Open full analytics &rarr;</a></div>
      </div>
    </div>
  </div>`;
}

async function loadData(){const btn=document.getElementById('refreshBtn');if(btn)btn.disabled=true;const result=await apiFetch('/stats');if(!result){renderLogin();return}data=result;renderDashboard();if(btn)btn.disabled=false}
function logout(){authToken=null;localStorage.removeItem('admin_token');renderLogin()}
function init(){authToken=localStorage.getItem('admin_token');if(authToken){loadData().catch(()=>{authToken=null;localStorage.removeItem('admin_token');renderLogin()})}else{renderLogin()}setInterval(()=>{if(authToken)loadData()},REFRESH_INTERVAL)}
init();
</script>
</body>
</html