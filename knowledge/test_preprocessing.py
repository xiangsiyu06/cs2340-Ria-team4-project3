from unittest import TestCase

from knowledge.preprocessing import Section, prepare_chunks, split_pdf_columns


class PreprocessingTests(TestCase):
    def test_preserves_rules_and_page_numbers(self):
        sections = [
            Section("  CS  1301   AND CS 1331\r\n", page_number=2),
            Section("  ", page_number=3),
            Section("Requirement    Credits\nCS 1332    3", page_number=4),
        ]
        chunks = prepare_chunks(sections)
        self.assertEqual([chunk.page_number for chunk in chunks], [2, 4])
        self.assertEqual(chunks[0].text, "CS 1301 AND CS 1331")
        self.assertEqual(chunks[1].text, "Requirement Credits\nCS 1332 3")

    def test_long_sections_are_bounded_and_repeat_the_context(self):
        section = Section(" ".join(["CS 1331 OR CS 1301."] * 20), heading="Core")
        chunks = prepare_chunks([section], limit=90, overlap=20)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.text) <= 90 for chunk in chunks))
        self.assertTrue(all(chunk.heading == "Core" for chunk in chunks))
        self.assertEqual(chunks, prepare_chunks([section], limit=90, overlap=20))


class PdfLayoutTests(TestCase):
    def test_two_column_layout_preserves_each_columns_reading_order(self):
        left = [f"CS {1300 + i} Introduction to Computing" for i in range(10)]
        right = [f"MATH {1500 + i} Discrete Mathematics" for i in range(10)]
        layout = [f"{a:48}{b}" for a, b in zip(left, right)]
        self.assertEqual(split_pdf_columns(layout), [left, right])

    def test_one_column_table_does_not_split_off_credit_counts(self):
        rows = [f"CS {1300 + i} Introduction to Computing                3" for i in range(10)]
        self.assertEqual(split_pdf_columns(rows), [rows])

    def test_wide_requirement_cells_stay_with_their_course_rows(self):
        rows = [
            f"{f'CS {1300 + i} Introduction to Computing':55}Requires departmental approval | 3"
            for i in range(10)
        ]
        self.assertEqual(split_pdf_columns(rows), [rows])
