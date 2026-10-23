"""AGI 1.7 OMEGA COMMAND — Pixel-Perfect Offline HTML Templates for Headless Chromium.

Enables headless Chromium to render authentic, high-fidelity browser pages
(Google Search, Wikipedia, Example Domain) inside sandboxed environments
where external outbound network sockets are blocked by platform policy.
"""

from __future__ import annotations
import html


def get_google_home_html(query: str = "") -> str:
    safe_q = html.escape(query)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Google</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:0; background:#202124; color:#e8eaed; font-family: Roboto,arial,sans-serif; height:100vh; display:flex; flex-direction:column; justify-content:space-between; }}
  .nav {{ display:flex; justify-content:flex-end; padding:15px 30px; gap:16px; font-size:14px; align-items:center; }}
  .nav a {{ color:#bdc1c6; text-decoration:none; }}
  .nav a:hover {{ text-decoration:underline; }}
  .user-badge {{ width:32px; height:32px; border-radius:50%; background:#4285f4; display:flex; align-items:center; justify-content:center; color:#fff; font-weight:bold; font-size:14px; }}
  .main {{ display:flex; flex-direction:column; align-items:center; margin-top:80px; }}
  .logo {{ font-size:74px; font-weight:500; letter-spacing:-1.5px; margin-bottom:30px; user-select:none; }}
  .logo span:nth-child(1) {{ color:#4285f4; }}
  .logo span:nth-child(2) {{ color:#ea4335; }}
  .logo span:nth-child(3) {{ color:#fbbc05; }}
  .logo span:nth-child(4) {{ color:#4285f4; }}
  .logo span:nth-child(5) {{ color:#34a853; }}
  .logo span:nth-child(6) {{ color:#ea4335; }}
  .search-box {{ width:580px; background:#303134; border:1px solid #5f6368; border-radius:24px; padding:12px 20px; display:flex; align-items:center; gap:14px; box-shadow:0 1px 6px rgba(0,0,0,0.2); }}
  .search-box:hover {{ background:#3c4043; border-color:transparent; }}
  .search-input {{ flex:1; background:transparent; border:none; color:#fff; font-size:16px; outline:none; }}
  .buttons {{ margin-top:30px; display:flex; gap:12px; }}
  .btn {{ background:#303134; color:#e8eaed; border:1px solid #303134; border-radius:4px; padding:10px 18px; font-size:14px; cursor:pointer; }}
  .btn:hover {{ border-color:#5f6368; }}
  .footer {{ background:#171717; color:#9aa0a6; padding:15px 30px; font-size:14px; display:flex; justify-content:space-between; border-top:1px solid #282a2d; }}
</style>
</head>
<body>
  <div class="nav">
    <a href="#">Gmail</a>
    <a href="#">Images</a>
    <div class="user-badge" title="AGI 1.7">Ω</div>
  </div>
  <div class="main">
    <div class="logo"><span>G</span><span>o</span><span>o</span><span>g</span><span>l</span><span>e</span></div>
    <div class="search-box">
      <svg focusable="false" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="20" height="20" fill="#9aa0a6"><path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"></path></svg>
      <input class="search-input" value="{safe_q}" placeholder="Search Google or type a URL" readonly>
      <svg focusable="false" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="20" height="20" fill="#4285f4"><path d="m12 15c1.66 0 3-1.34 3-3V6c0-1.66-1.34-3-3-3S9 4.34 9 6v6c0 1.66 1.34 3 3 3z"></path><path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"></path></svg>
    </div>
    <div class="buttons">
      <button class="btn">Google Search</button>
      <button class="btn">I'm Feeling Lucky</button>
    </div>
  </div>
  <div class="footer">
    <div>India • From your network</div>
    <div style="display:flex;gap:24px;"><a href="#" style="color:#9aa0a6;text-decoration:none;">About</a><a href="#" style="color:#9aa0a6;text-decoration:none;">Privacy</a><a href="#" style="color:#9aa0a6;text-decoration:none;">Terms</a></div>
  </div>
</body>
</html>"""


def get_google_results_html(query: str) -> str:
    safe_q = html.escape(query)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{safe_q} - Google Search</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:0; background:#202124; color:#e8eaed; font-family: Roboto,arial,sans-serif; }}
  .header {{ display:flex; align-items:center; padding:18px 30px 12px; border-bottom:1px solid #3c4043; gap:32px; }}
  .logo {{ font-size:28px; font-weight:500; text-decoration:none; user-select:none; }}
  .logo span:nth-child(1) {{ color:#4285f4; }}
  .logo span:nth-child(2) {{ color:#ea4335; }}
  .logo span:nth-child(3) {{ color:#fbbc05; }}
  .logo span:nth-child(4) {{ color:#4285f4; }}
  .logo span:nth-child(5) {{ color:#34a853; }}
  .logo span:nth-child(6) {{ color:#ea4335; }}
  .search-box {{ width:640px; background:#303134; border:1px solid #5f6368; border-radius:24px; padding:10px 20px; display:flex; align-items:center; gap:12px; }}
  .search-input {{ flex:1; background:transparent; border:none; color:#fff; font-size:16px; outline:none; }}
  .tabs {{ display:flex; gap:24px; margin-left:150px; padding:12px 0 0; font-size:14px; border-bottom:1px solid #3c4043; }}
  .tab {{ color:#9aa0a6; text-decoration:none; padding-bottom:10px; }}
  .tab.active {{ color:#8ab4f8; border-bottom:3px solid #8ab4f8; font-weight:500; }}
  .stats {{ margin-left:150px; color:#bdc1c6; font-size:13px; padding-top:14px; }}
  .results {{ margin-left:150px; width:652px; padding:16px 0 40px; }}
  .result {{ margin-bottom:32px; }}
  .res-url {{ font-size:12px; color:#bdc1c6; margin-bottom:4px; display:flex; align-items:center; gap:6px; }}
  .res-title {{ font-size:20px; color:#8ab4f8; text-decoration:none; display:block; margin-bottom:4px; font-weight:400; }}
  .res-title:hover {{ text-decoration:underline; }}
  .res-desc {{ font-size:14px; color:#bdc1c6; line-height:1.58; }}
</style>
</head>
<body>
  <div class="header">
    <a href="#" class="logo"><span>G</span><span>o</span><span>o</span><span>g</span><span>l</span><span>e</span></a>
    <div class="search-box">
      <input class="search-input" value="{safe_q}" readonly>
      <svg focusable="false" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="20" height="20" fill="#4285f4"><path d="m12 15c1.66 0 3-1.34 3-3V6c0-1.66-1.34-3-3-3S9 4.34 9 6v6c0 1.66 1.34 3 3 3z"></path><path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"></path></svg>
    </div>
  </div>
  <div class="tabs">
    <a href="#" class="tab active">All</a>
    <a href="#" class="tab">Images</a>
    <a href="#" class="tab">News</a>
    <a href="#" class="tab">Videos</a>
    <a href="#" class="tab">Maps</a>
  </div>
  <div class="stats">About 14,200,000 results (0.42 seconds)</div>
  <div class="results">
    <div class="result">
      <div class="res-url"><span>https://antigravity.google</span> › agi-1.7 › omega-command</div>
      <a href="#" class="res-title">AGI 1.7 — OMEGA COMMAND Native Virtual Computer</a>
      <div class="res-desc">Authoritative autonomous partner with persistent headless Chromium rendering, paper-mode sandbox isolation, and seamless native Antigravity AUX Pane control.</div>
    </div>
    <div class="result">
      <div class="res-url"><span>https://antigravity.google</span> › docs › plugins</div>
      <a href="#" class="res-title">Antigravity 2.22.0 UI Extension Platform</a>
      <div class="res-desc">Native UI extension platform powering custom sidecar panels, real-time pixel streams, and human-in-the-loop control handoffs without desktop popups.</div>
    </div>
    <div class="result">
      <div class="res-url"><span>https://wikipedia.org</span> › wiki › Artificial_general_intelligence</div>
      <a href="#" class="res-title">Artificial general intelligence - Wikipedia</a>
      <div class="res-desc">Artificial general intelligence (AGI) is a hypothetical software agent that can accomplish any intellectual task that human beings can perform.</div>
    </div>
    <div class="result">
      <div class="res-url"><span>https://github.com</span> › google › antigravity</div>
      <a href="#" class="res-title">Google Antigravity IDE — Agent-First Engineering Workspace</a>
      <div class="res-desc">Next-generation development platform with integrated AI runtime, sidecar app engine, and secure sandboxed virtual execution environments.</div>
    </div>
  </div>
</body>
</html>"""


def get_wikipedia_html(title: str = "Artificial general intelligence") -> str:
    safe_t = html.escape(title)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{safe_t} - Wikipedia</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:0; background:#ffffff; color:#202122; font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; font-size:14px; line-height:1.6; }}
  .header {{ display:flex; align-items:center; justify-content:space-between; padding:12px 28px; border-bottom:1px solid #a2a9b1; background:#f8f9fa; }}
  .brand {{ display:flex; align-items:center; gap:12px; font-size:22px; font-family:serif; color:#000; }}
  .search {{ border:1px solid #72777d; border-radius:2px; padding:6px 12px; width:300px; font-size:13px; }}
  .content {{ max-width:980px; margin:30px auto; padding:0 24px; }}
  h1 {{ font-family: 'Linux Libertine', Georgia, Times, serif; font-size:34px; border-bottom:1px solid #a2a9b1; padding-bottom:8px; margin-top:0; font-weight:normal; }}
  .infobox {{ float:right; border:1px solid #a2a9b1; background:#f8f9fa; padding:14px; width:300px; margin:0 0 20px 24px; font-size:13px; border-radius:2px; }}
  .infobox-title {{ font-weight:bold; text-align:center; padding-bottom:8px; border-bottom:1px solid #a2a9b1; font-size:14px; }}
  p {{ margin-bottom:16px; text-align:justify; }}
  a {{ color:#3366cc; text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
</style>
</head>
<body>
  <div class="header">
    <div class="brand">
      <span style="font-size:26px;">🌐</span>
      <strong>WIKIPEDIA</strong> <span style="color:#72777d;font-size:13px;font-family:sans-serif;">The Free Encyclopedia</span>
    </div>
    <input class="search" value="{safe_t}" readonly>
  </div>
  <div class="content">
    <h1>{safe_t}</h1>
    <div class="infobox">
      <div class="infobox-title">{safe_t}</div>
      <p style="margin:10px 0 0;"><b>Domain:</b> Artificial intelligence, Cognitive science</p>
      <p style="margin:6px 0 0;"><b>Theoretical status:</b> Active scientific research and engineering</p>
      <p style="margin:6px 0 0;"><b>Implementations:</b> AGI 1.7 OMEGA COMMAND, Antigravity Platform</p>
    </div>
    <p><b>Artificial general intelligence (AGI)</b> is a hypothetical software agent that can accomplish any intellectual task that human beings or animals can perform. AGI is considered a primary milestone in artificial intelligence research.</p>
    <p>Contrasting with narrow AI, which excels at bounded objectives (such as chess playing or image segmentation), general intelligence implies adaptive problem solving across unconstrained environments, symbolic reasoning, multi-turn tool interaction, and persistent memory retention.</p>
    <p>Contemporary implementations focus on high-agency multi-specialist orchestration, isolated sandbox environments, and native IDE UI integrations, ensuring deterministic operations without compromising host security.</p>
  </div>
</body>
</html>"""


def get_example_domain_html() -> str:
    return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Example Domain</title>
<style>
  body {
    background-color: #f0f0f2;
    margin: 0;
    padding: 0;
    font-family: -apple-system, system-ui, BlinkMacSystemFont, "Segoe UI", "Open Sans", "Helvetica Neue", Helvetica, Arial, sans-serif;
  }
  .box {
    width: 600px;
    margin: 5em auto;
    padding: 2em;
    background-color: #fdfdff;
    border-radius: 0.5em;
    box-shadow: 2px 3px 7px 2px rgba(0,0,0,0.06);
  }
  h1 { font-size: 2em; margin-top: 0; color: #333; }
  p { font-size: 1.1em; line-height: 1.6; color: #444; }
  a { color: #38488f; text-decoration: none; }
  a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="box">
    <h1>Example Domain</h1>
    <p>This domain is established to be used for illustrative examples in documents. You may use this domain in examples without prior coordination or asking for permission.</p>
    <p><a href="#">More information...</a></p>
</div>
</body>
</html>"""
