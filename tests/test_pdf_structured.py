from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from pdf_field_extractor import PdfNoFieldsError, extract_pdf_fields
from pdf_fill_manager import PdfFillManager
from pdf_schema_builder import build_json_schema, parse_json_object, parse_json_object_result, validate_pdf_field_values
from pdf_template_manager import PdfTemplateManager


class PdfStructuredTests(unittest.TestCase):
    def test_extract_fields_from_acroform(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "form.pdf"
            create_test_acroform_pdf(pdf_path)

            fields = extract_pdf_fields(pdf_path)

            names = {field["name"] for field in fields}
            self.assertEqual(names, {"patient_nom", "accord_patient"})
            self.assertEqual(next(field for field in fields if field["name"] == "patient_nom")["type"], "text")
            checkbox = next(field for field in fields if field["name"] == "accord_patient")
            self.assertEqual(checkbox["type"], "checkbox")
            self.assertIn("Yes", checkbox["options"])

    def test_pdf_without_fields_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "flat.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=300)
            with pdf_path.open("wb") as handle:
                writer.write(handle)

            with self.assertRaises(PdfNoFieldsError):
                extract_pdf_fields(pdf_path)

    def test_template_save_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_pdf = Path(tmp) / "form.pdf"
            create_test_acroform_pdf(source_pdf)
            manager = PdfTemplateManager(Path(tmp) / "templates")

            metadata = manager.import_template(source_pdf, name="Certificat test")
            loaded = manager.get_template(metadata["id"])
            fields = manager.load_fields(metadata["id"])

            self.assertEqual(loaded["name"], "Certificat test")
            self.assertTrue(Path(loaded["template_path"]).exists())
            self.assertEqual(len(fields), 2)

    def test_schema_and_json_validation(self):
        fields = [
            {"name": "patient_nom", "label": "Nom", "type": "text", "required": True},
            {"name": "accord_patient", "label": "Accord", "type": "checkbox", "required": False},
        ]
        schema = build_json_schema(fields)
        parsed = parse_json_object('```json\n{"patient_nom":"Dupont","accord_patient":"oui","intrus":"x"}\n```')
        values, issues = validate_pdf_field_values(parsed, fields)

        self.assertEqual(schema["properties"]["accord_patient"]["type"], "boolean")
        self.assertEqual(schema["required"], [])
        self.assertEqual(values["patient_nom"], "Dupont")
        self.assertIs(values["accord_patient"], True)
        self.assertTrue(any(issue["field"] == "intrus" for issue in issues))

        with self.assertRaises(ValueError):
            parse_json_object("pas du json")

    def test_truncated_json_response_recovers_complete_fields(self):
        result = parse_json_object_result(
            '```json\n{"patient_nom":"Dupont","accord_patient":false,"p2_date_'
        )

        self.assertTrue(result.recovered_partial)
        self.assertEqual(result.values["patient_nom"], "Dupont")
        self.assertIs(result.values["accord_patient"], False)

    def test_missing_or_empty_pdf_fields_are_not_added_to_values(self):
        fields = [
            {"name": "patient_nom", "label": "Nom", "type": "text", "required": True},
            {"name": "accord_patient", "label": "Accord", "type": "checkbox", "required": False},
        ]

        values, issues = validate_pdf_field_values({"patient_nom": "", "accord_patient": ""}, fields)

        self.assertEqual(values, {})
        self.assertEqual(issues, [])

    def test_fill_pdf_does_not_overwrite_template_and_sets_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            template_pdf = Path(tmp) / "form.pdf"
            output_pdf = Path(tmp) / "filled.pdf"
            create_test_acroform_pdf(template_pdf)
            fields = extract_pdf_fields(template_pdf)

            result = PdfFillManager().fill_pdf(
                template_pdf,
                {"patient_nom": "Dupont", "accord_patient": True},
                output_pdf,
                fields=fields,
            )

            self.assertEqual(result.output_path, output_pdf)
            self.assertTrue(output_pdf.exists())
            self.assertNotEqual(template_pdf.read_bytes(), output_pdf.read_bytes())

            original_fields = PdfReader(str(template_pdf)).get_fields()
            filled_fields = PdfReader(str(output_pdf)).get_fields()
            self.assertEqual(original_fields["patient_nom"].get("/V"), "")
            self.assertEqual(filled_fields["patient_nom"].get("/V"), "Dupont")
            self.assertEqual(str(filled_fields["accord_patient"].get("/V")), "/Yes")

    def test_fill_pdf_ignores_empty_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            template_pdf = Path(tmp) / "form.pdf"
            output_pdf = Path(tmp) / "filled.pdf"
            create_test_acroform_pdf(template_pdf)
            fields = extract_pdf_fields(template_pdf)

            result = PdfFillManager().fill_pdf(
                template_pdf,
                {"patient_nom": "", "accord_patient": False},
                output_pdf,
                fields=fields,
            )

            self.assertEqual(result.filled_fields, [])
            self.assertIn("patient_nom", result.ignored_fields)
            self.assertIn("accord_patient", result.ignored_fields)
            filled_fields = PdfReader(str(output_pdf)).get_fields()
            self.assertEqual(filled_fields["patient_nom"].get("/V"), "")
            self.assertEqual(str(filled_fields["accord_patient"].get("/V")), "/Off")


def create_test_acroform_pdf(path: Path) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    fields = []
    annotations = []

    text_field = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject("patient_nom"),
            NameObject("/V"): TextStringObject(""),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Rect"): ArrayObject([NumberObject(50), NumberObject(250), NumberObject(250), NumberObject(270)]),
            NameObject("/F"): NumberObject(4),
            NameObject("/P"): page.indirect_reference,
        }
    )
    text_ref = writer._add_object(text_field)
    fields.append(text_ref)
    annotations.append(text_ref)

    yes_stream = DecodedStreamObject()
    yes_stream.set_data(b"")
    off_stream = DecodedStreamObject()
    off_stream.set_data(b"")
    yes_ref = writer._add_object(yes_stream)
    off_ref = writer._add_object(off_stream)

    checkbox = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Btn"),
            NameObject("/T"): TextStringObject("accord_patient"),
            NameObject("/V"): NameObject("/Off"),
            NameObject("/AS"): NameObject("/Off"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Rect"): ArrayObject([NumberObject(50), NumberObject(220), NumberObject(65), NumberObject(235)]),
            NameObject("/F"): NumberObject(4),
            NameObject("/P"): page.indirect_reference,
            NameObject("/AP"): DictionaryObject(
                {
                    NameObject("/N"): DictionaryObject(
                        {
                            NameObject("/Yes"): yes_ref,
                            NameObject("/Off"): off_ref,
                        }
                    )
                }
            ),
        }
    )
    checkbox_ref = writer._add_object(checkbox)
    fields.append(checkbox_ref)
    annotations.append(checkbox_ref)

    page[NameObject("/Annots")] = ArrayObject(annotations)
    writer._root_object.update(
        {
            NameObject("/AcroForm"): DictionaryObject(
                {
                    NameObject("/Fields"): ArrayObject(fields),
                    NameObject("/NeedAppearances"): BooleanObject(True),
                }
            )
        }
    )

    with path.open("wb") as handle:
        writer.write(handle)


if __name__ == "__main__":
    unittest.main()
