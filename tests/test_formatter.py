import unittest

from output.formatter import format_ai_output


class FormatAiOutputTests(unittest.TestCase):
    def test_markdown_still_renders(self):
        html = format_ai_output("**Gym** at 2 PM\n\n- stretch\n- lift")
        self.assertIn("<strong>Gym</strong>", html)
        self.assertIn("<li>stretch</li>", html)

    def test_raw_html_is_escaped(self):
        html = format_ai_output("<script>alert(1)</script>\n\nhi <img src=x onerror=alert(1)>")
        self.assertNotIn("<script", html)
        self.assertNotIn("<img", html)

    def test_unsafe_links_and_event_handlers_are_removed(self):
        html = format_ai_output('[a](javascript:alert(1)) [b](https://example.com){: onclick="alert(1)" }')
        self.assertNotIn("javascript:", html)
        self.assertNotIn("onclick", html)
        self.assertIn('href="https://example.com"', html)


if __name__ == "__main__":
    unittest.main()
