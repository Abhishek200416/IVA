"""
Unit tests for Creative UI/UX Design Engine & Anti-AI-Slop Linter
Verifies token generation across all 8 archetypes, AI-slop pattern detection,
clean design validation, and prototype HTML generation.
"""

import unittest
import sys
import os

# Add pt root to path
pt_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if pt_root not in sys.path:
    sys.path.insert(0, pt_root)

from agents.IVA.engine.agi17.capabilities.creative_design_engine import (
    DesignArchetype,
    TokenSystemFactory,
    AntiAiSlopLinter,
    CreativePrototypeSynthesizer,
)


class TestCreativeDesignEngine(unittest.TestCase):

    def test_all_eight_archetypes_generate_valid_tokens(self):
        """Verify each of the 8 archetypes generates complete, non-empty tokens."""
        for archetype in DesignArchetype:
            tokens = TokenSystemFactory.get_tokens(archetype)
            self.assertEqual(tokens.archetype, archetype)
            self.assertTrue(tokens.bg_primary.startswith(("#", "rgb")))
            self.assertTrue(tokens.bg_surface.startswith(("#", "rgb")))
            self.assertTrue(tokens.accent_primary.startswith(("#", "rgb")))
            self.assertIsNotNone(tokens.font_display)
            self.assertIsNotNone(tokens.font_mono)
            self.assertIsNotNone(tokens.radius_md)

            css_vars = tokens.to_css_variables()
            self.assertIn(":root", css_vars)
            self.assertIn("--bg-primary:", css_vars)
            self.assertIn("--accent-primary:", css_vars)
            self.assertIn("--font-display:", css_vars)

    def test_swiss_modernist_has_sharp_zero_radius(self):
        """Swiss modernist style strictly requires 0px radius and high-contrast rules."""
        tokens = TokenSystemFactory.get_tokens(DesignArchetype.SWISS_MODERNIST)
        self.assertEqual(tokens.radius_sm, "0px")
        self.assertEqual(tokens.radius_md, "0px")
        self.assertEqual(tokens.radius_lg, "0px")
        self.assertEqual(tokens.shadow_sm, "none")
        self.assertIn("Akzidenz-Grotesk", tokens.font_display)

    def test_precision_industrial_uses_tight_radius_and_mono(self):
        """Precision industrial requires tight 2-4px radius and aerospace amber/mono."""
        tokens = TokenSystemFactory.get_tokens(DesignArchetype.PRECISION_INDUSTRIAL)
        self.assertEqual(tokens.radius_sm, "2px")
        self.assertEqual(tokens.radius_md, "4px")
        self.assertIn("JetBrains Mono", tokens.font_mono)
        self.assertEqual(tokens.accent_primary, "#ff8c00")

    def test_anti_ai_slop_linter_detects_purple_gradient_cliche(self):
        """Linter must flag generic purple-indigo gradients with CRITICAL severity."""
        slop_code = """
        <div class="bg-gradient-to-r from-purple-500 to-indigo-500 rounded-2xl p-6">
            <h3>Awesome Feature</h3>
        </div>
        """
        result = AntiAiSlopLinter.audit_markup(slop_code)
        self.assertFalse(result.is_slop_free)
        self.assertGreater(result.slop_score, 0.3)
        rule_ids = [v.rule_id for v in result.violations]
        self.assertIn("SLOP-001-PURPLE-CYAN-GRADIENT", rule_ids)

    def test_anti_ai_slop_linter_detects_backdrop_blur(self):
        """Linter must flag gratuitous backdrop-blur."""
        slop_code = """
        <div class="backdrop-blur bg-white/5 rounded-2xl border border-white/10">
            <p>Illegible card content</p>
        </div>
        """
        result = AntiAiSlopLinter.audit_markup(slop_code)
        self.assertFalse(result.is_slop_free)
        rule_ids = [v.rule_id for v in result.violations]
        self.assertIn("SLOP-002-ILLEGIBLE-BLUR-CARD", rule_ids)

    def test_anti_ai_slop_linter_detects_marketing_cliches(self):
        """Linter must flag generic marketing headlines."""
        slop_code = "<h1>Supercharge Your Workflow With AI</h1>"
        result = AntiAiSlopLinter.audit_markup(slop_code)
        self.assertFalse(result.is_slop_free)
        rule_ids = [v.rule_id for v in result.violations]
        self.assertIn("SLOP-005-GENERIC-MARKETING-HERO", rule_ids)

    def test_anti_ai_slop_linter_approves_clean_human_design(self):
        """Linter must give 0.0 slop score to clean, bespoke human craft."""
        clean_code = """
        <div class="theme-industrial" style="background:#0e1013; border:1px solid rgba(255,255,255,0.08); padding:16px;">
            <div style="font-family:'JetBrains Mono'; font-size:12px; color:#ff8c00;">SVI_VOLATILITY_MONITOR</div>
            <div style="font-size:24px; font-weight:700; color:#e6edf3;">24,890.45</div>
        </div>
        """
        result = AntiAiSlopLinter.audit_markup(clean_code)
        self.assertTrue(result.is_slop_free)
        self.assertEqual(result.slop_score, 0.0)
        self.assertEqual(len(result.violations), 0)

    def test_creative_prototype_synthesizer_generates_html(self):
        """Synthesizer must produce valid HTML containing all 4 showcase archetypes."""
        html = CreativePrototypeSynthesizer.generate_showcase_html()
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Precision Industrial", html)
        self.assertIn("Swiss Modernist", html)
        self.assertIn("Warm Editorial", html)
        self.assertIn("Neo-Brutalist", html)
        self.assertIn("switchTab", html)


if __name__ == "__main__":
    unittest.main()
