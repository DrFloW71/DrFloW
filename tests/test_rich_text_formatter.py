from __future__ import annotations

import unittest

from rich_text_formatter import RichTextPayload, combine_weda_rich_text_payloads, format_weda_rich_text


class RichTextFormatterTests(unittest.TestCase):
    def test_markdown_is_removed_from_text_and_preserved_as_html(self):
        payload = format_weda_rich_text("# Synthese\n\n**Toux** et __alerte__\n- revoir dans 48 h")

        self.assertEqual(payload.text, "Synthese\n\nToux et alerte\n- revoir dans 48 h")
        self.assertIn("<strong><u>Synthese</u></strong>", payload.html)
        self.assertIn("<strong>Toux</strong>", payload.html)
        self.assertIn("<u>alerte</u>", payload.html)
        self.assertIn("&#8226; revoir dans 48 h", payload.html)
        self.assertNotIn("**", payload.text)
        self.assertNotIn("__", payload.text)

    def test_only_safe_inline_html_tags_are_preserved(self):
        payload = format_weda_rich_text("<script>alert(1)</script><u>Important</u><br><b>OK</b>")

        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", payload.html)
        self.assertIn("<u>Important</u>", payload.html)
        self.assertIn("<br>", payload.html)
        self.assertIn("<strong>OK</strong>", payload.html)
        self.assertEqual(payload.text, "alert(1)Important\nOK")

    def test_plain_medical_section_labels_are_formatted(self):
        payload = format_weda_rich_text("Synthese\nMotif : toux\nTA : 130/80\nConclusion : bronchite")

        self.assertEqual(payload.text, "Synthese\nMotif : toux\nTA : 130/80\nConclusion : bronchite")
        self.assertIn("<strong><u>Synthese</u></strong>", payload.html)
        self.assertIn("<strong><u>Motif :</u></strong> toux", payload.html)
        self.assertIn("TA : 130/80", payload.html)
        self.assertNotIn("<strong><u>TA :</u></strong>", payload.html)
        self.assertIn("<strong><u>Conclusion :</u></strong> bronchite", payload.html)

    def test_combines_payloads_with_blank_line_separator(self):
        combined = combine_weda_rich_text_payloads([
            RichTextPayload(text="Premier", html="<strong>Premier</strong>"),
            RichTextPayload(text="Second", html="<u>Second</u>"),
        ])

        self.assertEqual(combined.text, "Premier\n\nSecond")
        self.assertEqual(combined.html, "<strong>Premier</strong><br><br><u>Second</u>")

    def test_prompt_authored_outer_blank_lines_are_preserved(self):
        payload = format_weda_rich_text("\n**Titre libre**\n- ligne clinique\n")

        self.assertEqual(payload.text, "\nTitre libre\n- ligne clinique\n")
        self.assertEqual(payload.html, "<br><strong>Titre libre</strong><br>&#8226; ligne clinique<br>")

    def test_consultation_motif_blocks_keep_prompt_line_breaks(self):
        payload = format_weda_rich_text(
            "**Motif 1 : toux**\n"
            "Anamnèse : toux sèche depuis 48 h.\n"
            "Pas de dyspnée.\n\n"
            "__Motif 2 : renouvellement__\n"
            "Anamnèse : traitement bien toléré."
        )

        self.assertEqual(
            payload.text,
            "Motif 1 : toux\n"
            "Anamnèse : toux sèche depuis 48 h.\n"
            "Pas de dyspnée.\n\n"
            "Motif 2 : renouvellement\n"
            "Anamnèse : traitement bien toléré.",
        )
        self.assertIn(
            "<strong>Motif 1 : toux</strong><br>Anamnèse : toux sèche depuis 48 h.<br>Pas de dyspnée.",
            payload.html,
        )
        self.assertIn("<br><br>", payload.html)
        self.assertIn("<u>Motif 2 : renouvellement</u><br>Anamnèse : traitement bien toléré.", payload.html)

    def test_standalone_medical_motif_spacing_is_preserved_from_prompt(self):
        payload = format_weda_rich_text(
            "Pylorite\n\n"
            "• Fièvre 39 °C. Signes fonctionnels urinaires.\n"
            "• Abdomen souple.\n"
            "  -> PYLORITE: IRBESARTAN renouvelé\n\n"
            "Douleur d'épaule\n\n"
            "• Douleur d'épaule depuis 3 semaines.\n"
            "• Injection en aseptie stricte et selon les recommandations (DIPROSTENE)\n"
            "  -> DOULEUR D'ÉPAULE: DIPROSTENE injecté"
        )

        self.assertEqual(
            payload.text,
            "Pylorite\n\n"
            "• Fièvre 39 °C. Signes fonctionnels urinaires.\n"
            "• Abdomen souple.\n"
            "-> PYLORITE: IRBESARTAN renouvelé\n\n"
            "Douleur d'épaule\n\n"
            "• Douleur d'épaule depuis 3 semaines.\n"
            "• Injection en aseptie stricte et selon les recommandations (DIPROSTENE)\n"
            "-> DOULEUR D'ÉPAULE: DIPROSTENE injecté",
        )
        self.assertIn(
            "Pylorite<br><br>• Fièvre 39 °C. Signes fonctionnels urinaires.<br>"
            "• Abdomen souple.<br>  -&gt; PYLORITE: IRBESARTAN renouvelé",
            payload.html,
        )
        self.assertIn("<br><br>Douleur d&#x27;épaule<br><br>•", payload.html)
        self.assertNotIn("Pylorite •", payload.html)


if __name__ == "__main__":
    unittest.main()
