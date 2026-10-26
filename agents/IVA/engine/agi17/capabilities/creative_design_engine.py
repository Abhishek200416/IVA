"""
Creative UI/UX Design Engine & Anti-AI-Slop Linter
AGI 1.7 / IVA Autonomous Capability Module

Provides algorithmic generation of bespoke design token systems across 8 archetypes,
automated linting for generic AI UI anti-patterns ("AI slop"), and multi-variant
prototype synthesis.
"""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Dict, List, Optional, Tuple


class DesignArchetype(str, Enum):
    PRECISION_INDUSTRIAL = "precision_industrial"
    SWISS_MODERNIST = "swiss_modernist"
    WARM_EDITORIAL = "warm_editorial"
    NEO_BRUTALIST = "neo_brutalist"
    ORGANIC_MINIMALIST = "organic_minimalist"
    RETRO_CYBERDECK = "retro_cyberdeck"
    FINANCIAL_TERMINAL = "financial_terminal"
    TACTILE_SKEUOMORPHIC = "tactile_skeuomorphic"


@dataclass
class DesignTokens:
    archetype: DesignArchetype
    bg_primary: str
    bg_surface: str
    bg_surface_raised: str
    border_subtle: str
    border_strong: str
    text_primary: str
    text_muted: str
    accent_primary: str
    accent_hover: str
    accent_subtle: str
    status_success: str
    status_warning: str
    status_danger: str
    font_display: str
    font_body: str
    font_mono: str
    radius_sm: str
    radius_md: str
    radius_lg: str
    shadow_sm: str
    shadow_md: str
    shadow_lg: str
    transition_spring: str

    def to_css_variables(self) -> str:
        """Export as CSS custom properties block."""
        return f"""/* Design Tokens: {self.archetype.value} */
:root {{
  --bg-primary: {self.bg_primary};
  --bg-surface: {self.bg_surface};
  --bg-surface-raised: {self.bg_surface_raised};
  --border-subtle: {self.border_subtle};
  --border-strong: {self.border_strong};
  --text-primary: {self.text_primary};
  --text-muted: {self.text_muted};
  --accent-primary: {self.accent_primary};
  --accent-hover: {self.accent_hover};
  --accent-subtle: {self.accent_subtle};
  --status-success: {self.status_success};
  --status-warning: {self.status_warning};
  --status-danger: {self.status_danger};
  --font-display: {self.font_display};
  --font-body: {self.font_body};
  --font-mono: {self.font_mono};
  --radius-sm: {self.radius_sm};
  --radius-md: {self.radius_md};
  --radius-lg: {self.radius_lg};
  --shadow-sm: {self.shadow_sm};
  --shadow-md: {self.shadow_md};
  --shadow-lg: {self.shadow_lg};
  --ease-spring: {self.transition_spring};
}}"""


class TokenSystemFactory:
    """Produces authentic, character-rich design token sets for each archetype."""

    @staticmethod
    def get_tokens(archetype: DesignArchetype) -> DesignTokens:
        if archetype == DesignArchetype.PRECISION_INDUSTRIAL:
            return DesignTokens(
                archetype=archetype,
                bg_primary="#0e1013",
                bg_surface="#15181e",
                bg_surface_raised="#1b2028",
                border_subtle="rgba(255, 255, 255, 0.08)",
                border_strong="rgba(255, 255, 255, 0.18)",
                text_primary="#e6edf3",
                text_muted="#7d8590",
                accent_primary="#ff8c00",  # Aerospace instrument amber
                accent_hover="#ffa733",
                accent_subtle="rgba(255, 140, 0, 0.12)",
                status_success="#00e676",
                status_warning="#ffd600",
                status_danger="#ff3d00",
                font_display="'DIN Next', 'Geist', -apple-system, sans-serif",
                font_body="'Geist', -apple-system, sans-serif",
                font_mono="'JetBrains Mono', 'IBM Plex Mono', monospace",
                radius_sm="2px",
                radius_md="4px",
                radius_lg="6px",
                shadow_sm="0 1px 2px rgba(0,0,0,0.5)",
                shadow_md="0 4px 8px rgba(0,0,0,0.6)",
                shadow_lg="0 12px 24px rgba(0,0,0,0.8)",
                transition_spring="cubic-bezier(0.16, 1, 0.3, 1)",
            )

        elif archetype == DesignArchetype.SWISS_MODERNIST:
            return DesignTokens(
                archetype=archetype,
                bg_primary="#f4f4f0",
                bg_surface="#ffffff",
                bg_surface_raised="#eaeae6",
                border_subtle="rgba(0, 0, 0, 0.12)",
                border_strong="#000000",
                text_primary="#111111",
                text_muted="#555555",
                accent_primary="#e60000",  # Swiss poster crimson
                accent_hover="#cc0000",
                accent_subtle="rgba(230, 0, 0, 0.08)",
                status_success="#008000",
                status_warning="#d97706",
                status_danger="#e60000",
                font_display="'Akzidenz-Grotesk', 'Helvetica Neue', 'Arial', sans-serif",
                font_body="'Helvetica Neue', 'Arial', sans-serif",
                font_mono="'Courier New', monospace",
                radius_sm="0px",
                radius_md="0px",
                radius_lg="0px",
                shadow_sm="none",
                shadow_md="none",
                shadow_lg="none",
                transition_spring="cubic-bezier(0.2, 0, 0, 1)",
            )

        elif archetype == DesignArchetype.WARM_EDITORIAL:
            return DesignTokens(
                archetype=archetype,
                bg_primary="#fbf9f5",
                bg_surface="#ffffff",
                bg_surface_raised="#f2ece1",
                border_subtle="rgba(60, 45, 30, 0.12)",
                border_strong="rgba(60, 45, 30, 0.28)",
                text_primary="#1c1917",
                text_muted="#665e57",
                accent_primary="#963d1a",  # Warm terracotta ink
                accent_hover="#7a3014",
                accent_subtle="rgba(150, 61, 26, 0.08)",
                status_success="#2d6a4f",
                status_warning="#b07d1a",
                status_danger="#963d1a",
                font_display="'Fraunces', 'Playfair Display', serif",
                font_body="'Newsreader', 'Georgia', serif",
                font_mono="'Berkeley Mono', 'Courier Prime', monospace",
                radius_sm="3px",
                radius_md="6px",
                radius_lg="8px",
                shadow_sm="0 1px 3px rgba(60, 45, 30, 0.06)",
                shadow_md="0 4px 12px rgba(60, 45, 30, 0.08)",
                shadow_lg="0 16px 32px rgba(60, 45, 30, 0.10)",
                transition_spring="cubic-bezier(0.25, 1, 0.5, 1)",
            )

        elif archetype == DesignArchetype.NEO_BRUTALIST:
            return DesignTokens(
                archetype=archetype,
                bg_primary="#fdfbf7",
                bg_surface="#ffffff",
                bg_surface_raised="#fff4cc",
                border_subtle="#000000",
                border_strong="#000000",
                text_primary="#000000",
                text_muted="#4a4a4a",
                accent_primary="#ffdd00",  # High-energy hazard yellow
                accent_hover="#ffd000",
                accent_subtle="rgba(255, 221, 0, 0.25)",
                status_success="#10b981",
                status_warning="#f59e0b",
                status_danger="#ef4444",
                font_display="'Space Grotesk', 'Syne', sans-serif",
                font_body="'Space Grotesk', system-ui, sans-serif",
                font_mono="'Space Mono', monospace",
                radius_sm="4px",
                radius_md="6px",
                radius_lg="8px",
                shadow_sm="2px 2px 0px #000000",
                shadow_md="4px 4px 0px #000000",
                shadow_lg="8px 8px 0px #000000",
                transition_spring="cubic-bezier(0.18, 0.89, 0.32, 1.28)",
            )

        elif archetype == DesignArchetype.ORGANIC_MINIMALIST:
            return DesignTokens(
                archetype=archetype,
                bg_primary="#f7f6f2",
                bg_surface="#ffffff",
                bg_surface_raised="#eeece4",
                border_subtle="rgba(40, 35, 30, 0.06)",
                border_strong="rgba(40, 35, 30, 0.14)",
                text_primary="#24211e",
                text_muted="#78736a",
                accent_primary="#3c4a3e",  # Deep Nordic forest moss
                accent_hover="#2e3a30",
                accent_subtle="rgba(60, 74, 62, 0.08)",
                status_success="#406343",
                status_warning="#af8438",
                status_danger="#9b443c",
                font_display="'Plus Jakarta Sans', sans-serif",
                font_body="'Plus Jakarta Sans', system-ui, sans-serif",
                font_mono="'JetBrains Mono', monospace",
                radius_sm="6px",
                radius_md="10px",
                radius_lg="16px",
                shadow_sm="0 2px 4px rgba(40, 35, 30, 0.03)",
                shadow_md="0 8px 24px rgba(40, 35, 30, 0.05)",
                shadow_lg="0 20px 40px rgba(40, 35, 30, 0.08)",
                transition_spring="cubic-bezier(0.16, 1, 0.3, 1)",
            )

        elif archetype == DesignArchetype.FINANCIAL_TERMINAL:
            return DesignTokens(
                archetype=archetype,
                bg_primary="#0b0e14",
                bg_surface="#111620",
                bg_surface_raised="#18202e",
                border_subtle="rgba(255, 255, 255, 0.06)",
                border_strong="rgba(255, 255, 255, 0.14)",
                text_primary="#eaedf1",
                text_muted="#6e7a8a",
                accent_primary="#00d2b4",  # High-visibility trading teal
                accent_hover="#00ebd0",
                accent_subtle="rgba(0, 210, 180, 0.12)",
                status_success="#00d2b4",  # Teal gain
                status_warning="#e5a93c",
                status_danger="#ff4e64",   # Crimson loss
                font_display="'Geist', -apple-system, sans-serif",
                font_body="'Geist', -apple-system, sans-serif",
                font_mono="'JetBrains Mono', monospace",
                radius_sm="2px",
                radius_md="4px",
                radius_lg="6px",
                shadow_sm="none",
                shadow_md="0 4px 12px rgba(0,0,0,0.5)",
                shadow_lg="0 8px 24px rgba(0,0,0,0.7)",
                transition_spring="linear",
            )

        # Default fallback: RETRO_CYBERDECK or TACTILE_SKEUOMORPHIC
        return DesignTokens(
            archetype=archetype,
            bg_primary="#050805",
            bg_surface="#0a120a",
            bg_surface_raised="#101d10",
            border_subtle="rgba(50, 255, 100, 0.15)",
            border_strong="rgba(50, 255, 100, 0.35)",
            text_primary="#32ff64",
            text_muted="#1a8c36",
            accent_primary="#ffb000",  # Phosphor amber
            accent_hover="#ffc433",
            accent_subtle="rgba(255, 176, 0, 0.15)",
            status_success="#32ff64",
            status_warning="#ffb000",
            status_danger="#ff3333",
            font_display="'Share Tech Mono', 'Courier New', monospace",
            font_body="'Share Tech Mono', monospace",
            font_mono="'Share Tech Mono', monospace",
            radius_sm="2px",
            radius_md="3px",
            radius_lg="4px",
            shadow_sm="0 0 5px rgba(50,255,100,0.2)",
            shadow_md="0 0 10px rgba(50,255,100,0.3)",
            shadow_lg="0 0 20px rgba(50,255,100,0.4)",
            transition_spring="step-start",
        )


@dataclass
class SlopViolation:
    rule_id: str
    description: str
    severity: str  # "CRITICAL", "HIGH", "MEDIUM"
    snippet: str
    recommendation: str


@dataclass
class SlopAuditResult:
    slop_score: float  # 0.0 (clean human craft) to 1.0 (pure AI slop)
    is_slop_free: bool
    violations: List[SlopViolation] = field(default_factory=list)


class AntiAiSlopLinter:
    """Linter that inspects CSS, HTML, and JSX code to detect generic AI design clichés."""

    SLOP_PATTERNS = [
        (
            "SLOP-001-PURPLE-CYAN-GRADIENT",
            re.compile(
                r"(from-purple-\d+|to-indigo-\d+|from-indigo-\d+|to-purple-\d+|#8b5cf6|#6366f1|linear-gradient\([^)]*purple[^)]*indigo[^)]*\))",
                re.IGNORECASE,
            ),
            "CRITICAL",
            "Generic electric purple/indigo gradient detected. Overused AI landing page cliché.",
            "Use characterful bespoke chromatic harmonies (Ochre/Slate, Ink/Cream, Forest/Brass).",
        ),
        (
            "SLOP-002-ILLEGIBLE-BLUR-CARD",
            re.compile(r"(backdrop-blur|backdrop-filter:\s*blur)", re.IGNORECASE),
            "HIGH",
            "Gratuitous glassmorphic backdrop-blur detected without verified legibility.",
            "Use opaque, tactile surfaces with razor-sharp 1px border contrast.",
        ),
        (
            "SLOP-003-UNIFORM-THREE-CARD-ROW",
            re.compile(r"(grid-cols-3|grid-template-columns:\s*repeat\(3,\s*1fr\))", re.IGNORECASE),
            "MEDIUM",
            "Uniform 3-column equidistant grid detected. High risk of cookie-cutter AI feature cards.",
            "Use asymmetrical layouts, Bento grids, or master-detail hierarchy.",
        ),
        (
            "SLOP-004-UNIFORM-ROUNDED-OVERKILL",
            re.compile(r"(rounded-2xl|rounded-3xl|border-radius:\s*(16px|24px|32px))", re.IGNORECASE),
            "MEDIUM",
            "Excessive rounded-2xl/3xl border radius on general containers.",
            "Calibrate corner geometry to archetype: 2-4px for technical precision, 0px for Swiss/brutalist.",
        ),
        (
            "SLOP-005-GENERIC-MARKETING-HERO",
            re.compile(
                r"(Supercharge Your|All-in-one platform|Unlock the power of|Next-generation)",
                re.IGNORECASE,
            ),
            "HIGH",
            "Cliché AI placeholder marketing headline detected.",
            "Write specific, concrete, high-information-density copy.",
        ),
    ]

    @classmethod
    def audit_markup(cls, code: str) -> SlopAuditResult:
        violations: List[SlopViolation] = []

        for rule_id, pattern, severity, desc, rec in cls.SLOP_PATTERNS:
            matches = list(pattern.finditer(code))
            for m in matches[:2]:  # Limit snippets to 2 per rule
                snippet = m.group(0)
                violations.append(
                    SlopViolation(
                        rule_id=rule_id,
                        description=desc,
                        severity=severity,
                        snippet=snippet,
                        recommendation=rec,
                    )
                )

        # Calculate slop score
        penalty_weights = {"CRITICAL": 0.35, "HIGH": 0.20, "MEDIUM": 0.10}
        total_penalty = sum(penalty_weights.get(v.severity, 0.05) for v in violations)
        slop_score = min(1.0, round(total_penalty, 2))

        return SlopAuditResult(
            slop_score=slop_score,
            is_slop_free=(len(violations) == 0),
            violations=violations,
        )


class CreativePrototypeSynthesizer:
    """Generates clean, interactive multi-variant HTML/CSS prototypes."""

    @staticmethod
    def generate_showcase_html() -> str:
        """Produces a self-contained multi-archetype interactive demo."""
        ind_tokens = TokenSystemFactory.get_tokens(DesignArchetype.PRECISION_INDUSTRIAL)
        swiss_tokens = TokenSystemFactory.get_tokens(DesignArchetype.SWISS_MODERNIST)
        ed_tokens = TokenSystemFactory.get_tokens(DesignArchetype.WARM_EDITORIAL)
        neo_tokens = TokenSystemFactory.get_tokens(DesignArchetype.NEO_BRUTALIST)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>IVA Creative UI/UX Showcase • Anti-AI-Slop Architecture</title>
  <style>
    /* Reset & Base */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: system-ui, -apple-system, sans-serif;
      background: #0d0f12;
      color: #e6edf3;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }}
    header {{
      padding: 16px 24px;
      background: #14181f;
      border-bottom: 1px solid rgba(255,255,255,0.08);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .badge {{
      background: #ff8c00;
      color: #000;
      font-size: 11px;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 3px;
      letter-spacing: 0.05em;
    }}
    .nav-tabs {{
      display: flex;
      gap: 8px;
    }}
    .tab-btn {{
      background: transparent;
      border: 1px solid rgba(255,255,255,0.12);
      color: #8b949e;
      padding: 8px 16px;
      font-size: 13px;
      font-weight: 500;
      border-radius: 4px;
      cursor: pointer;
      transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    }}
    .tab-btn:hover {{
      color: #fff;
      border-color: rgba(255,255,255,0.25);
    }}
    .tab-btn.active {{
      background: #21262d;
      color: #fff;
      border-color: #ff8c00;
    }}
    main {{
      flex: 1;
      padding: 32px;
      max-width: 1200px;
      margin: 0 auto;
      width: 100%;
    }}
    .variant-container {{
      display: none;
      animation: fadeIn 0.25s ease-out;
    }}
    .variant-container.active {{
      display: block;
    }}
    @keyframes fadeIn {{
      from {{ opacity: 0; transform: translateY(6px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    /* VARIANT 1: PRECISION INDUSTRIAL */
    .theme-industrial {{
      background: {ind_tokens.bg_primary};
      color: {ind_tokens.text_primary};
      border: 1px solid {ind_tokens.border_subtle};
      border-radius: {ind_tokens.radius_md};
      padding: 24px;
      font-family: {ind_tokens.font_mono};
    }}
    .industrial-header {{
      display: flex;
      justify-content: space-between;
      border-bottom: 1px solid {ind_tokens.border_subtle};
      padding-bottom: 12px;
      margin-bottom: 20px;
    }}
    .pulse-dot {{
      display: inline-block;
      width: 8px;
      height: 8px;
      background: #00e676;
      border-radius: 50%;
      margin-right: 6px;
      box-shadow: 0 0 8px #00e676;
    }}

    /* VARIANT 2: SWISS MODERNIST */
    .theme-swiss {{
      background: {swiss_tokens.bg_primary};
      color: {swiss_tokens.text_primary};
      border: 2px solid {swiss_tokens.border_strong};
      padding: 32px;
      font-family: {swiss_tokens.font_display};
    }}
    .swiss-title {{
      font-size: 38px;
      font-weight: 900;
      letter-spacing: -0.03em;
      line-height: 1.05;
      margin-bottom: 16px;
      text-transform: uppercase;
    }}
    .swiss-accent-bar {{
      width: 60px;
      height: 6px;
      background: {swiss_tokens.accent_primary};
      margin-bottom: 24px;
    }}

    /* VARIANT 3: WARM EDITORIAL */
    .theme-editorial {{
      background: {ed_tokens.bg_primary};
      color: {ed_tokens.text_primary};
      border: 1px solid {ed_tokens.border_subtle};
      border-radius: {ed_tokens.radius_md};
      padding: 40px;
      font-family: {ed_tokens.font_body};
    }}
    .editorial-headline {{
      font-family: {ed_tokens.font_display};
      font-size: 32px;
      font-style: italic;
      color: {ed_tokens.text_primary};
      margin-bottom: 16px;
      border-bottom: 1px solid {ed_tokens.border_subtle};
      padding-bottom: 12px;
    }}

    /* VARIANT 4: NEO-BRUTALIST */
    .theme-brutalist {{
      background: {neo_tokens.bg_primary};
      color: {neo_tokens.text_primary};
      border: 3px solid #000;
      border-radius: 6px;
      box-shadow: 6px 6px 0px #000;
      padding: 32px;
      font-family: {neo_tokens.font_display};
    }}
    .brutalist-btn {{
      background: {neo_tokens.accent_primary};
      color: #000;
      border: 2px solid #000;
      box-shadow: 3px 3px 0px #000;
      padding: 10px 20px;
      font-weight: 800;
      cursor: pointer;
      border-radius: 4px;
      transition: all 0.1s ease;
    }}
    .brutalist-btn:active {{
      transform: translate(2px, 2px);
      box-shadow: 1px 1px 0px #000;
    }}
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <span class="badge">IVA DESIGN ENGINE</span>
      <strong>Anti-AI-Slop Creative Architecture</strong>
    </div>
    <div class="nav-tabs">
      <button class="tab-btn active" onclick="switchTab('industrial')">1. Precision Industrial</button>
      <button class="tab-btn" onclick="switchTab('swiss')">2. Swiss Modernist</button>
      <button class="tab-btn" onclick="switchTab('editorial')">3. Warm Editorial</button>
      <button class="tab-btn" onclick="switchTab('brutalist')">4. Neo-Brutalist</button>
    </div>
  </header>

  <main>
    <!-- Variant 1: Industrial -->
    <div id="tab-industrial" class="variant-container active">
      <div class="theme-industrial">
        <div class="industrial-header">
          <div><span class="pulse-dot"></span>SYS_OPERATIONAL: TEL_INDEX_01</div>
          <div>LATENCY: 1.2ms [NIFTY_50_TICK]</div>
        </div>
        <p style="color:#7d8590; margin-bottom:16px;">// TELEMETRY MONITOR — HIGH-DENSITY MONOSPACED ERGONOMICS</p>
        <div style="display:grid; grid-template-columns: 2fr 1fr; gap:16px;">
          <div style="background:#15181e; border:1px solid rgba(255,255,255,0.08); padding:16px;">
            <div style="font-size:11px; color:#ff8c00;">SVI_VOLATILITY_SURFACE_OMEGA</div>
            <div style="font-size:24px; font-weight:700; margin:8px 0;">24,890.45 <span style="font-size:13px; color:#00e676;">+0.64%</span></div>
            <div style="font-size:12px; color:#7d8590;">AtmVol: 13.42 | Skew: -0.18 | Kurt: 1.04</div>
          </div>
          <div style="background:#15181e; border:1px solid rgba(255,255,255,0.08); padding:16px; display:flex; flex-direction:column; justify-content:center;">
            <div style="font-size:11px; color:#7d8590;">HOTKEYS</div>
            <div style="margin-top:6px; font-size:12px;"><strong>[SPACE]</strong> Pause | <strong>[E]</strong> Inspect | <strong>[Q]</strong> Abort</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Variant 2: Swiss Modernist -->
    <div id="tab-swiss" class="variant-container">
      <div class="theme-swiss">
        <div class="swiss-title">ARCHITECTURAL CLARITY</div>
        <div class="swiss-accent-bar"></div>
        <p style="font-size:18px; line-height:1.4; max-width:650px; margin-bottom:24px; color:#333;">
          Pure typographic discipline. No decorative dropshadows, no fake glassmorphic gradients. Structure is derived entirely from grid tension, contrast, and mathematical scale.
        </p>
        <div style="display:flex; gap:32px; border-top:1px solid #000; padding-top:16px;">
          <div><strong>01</strong> GRID RIGOR</div>
          <div><strong>02</strong> ASYMMETRIC CONTRAST</div>
          <div><strong>03</strong> ZERO DECORATIVE NOISE</div>
        </div>
      </div>
    </div>

    <!-- Variant 3: Warm Editorial -->
    <div id="tab-editorial" class="variant-container">
      <div class="theme-editorial">
        <div class="editorial-headline">The Philosophy of Tasteful Computation</div>
        <p style="font-size:17px; line-height:1.65; max-width:680px; margin-bottom:20px;">
          A humane user interface breathes like fine paper and ink. By rejecting the sterile dark-mode clichés of contemporary AI tools, we restore warm tactile dignity and quiet intellectual focus to the operator's workspace.
        </p>
        <div style="font-size:13px; color:#963d1a; font-weight:600; text-transform:uppercase; letter-spacing:0.05em;">
          Volume IV • Essay on Human-Agent Co-Design
        </div>
      </div>
    </div>

    <!-- Variant 4: Neo-Brutalist -->
    <div id="tab-brutalist" class="variant-container">
      <div class="theme-brutalist">
        <h2 style="font-size:32px; font-weight:900; margin-bottom:12px;">UNAPOLOGETIC UTILITY.</h2>
        <p style="font-size:16px; margin-bottom:24px; max-width:550px;">
          Crisp 3px black borders, tactile physical drop shadows, and high-impact functional buttons. Tactile feedback you can feel on every single click.
        </p>
        <button class="brutalist-btn">EXECUTE COMMAND ➔</button>
      </div>
    </div>
  </main>

  <script>
    function switchTab(name) {{
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.variant-container').forEach(c => c.classList.remove('active'));
      document.getElementById('tab-' + name).classList.add('active');
      event.target.classList.add('active');
    }}
  </script>
</body>
</html>"""
