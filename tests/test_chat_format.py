import unittest

from core.chat_format import split_fenced


class ChatFormatTests(unittest.TestCase):
    def test_splits_text_language_and_code(self):
        parts = split_fenced('Prima\n```python\nprint("ciao")\n```\nDopo')
        self.assertEqual(parts, [('text', '', 'Prima\n'),
                                 ('code', 'python', 'print("ciao")'),
                                 ('text', '', 'Dopo')])

    def test_empty_language_becomes_code(self):
        self.assertEqual(split_fenced('```\nx = 1\n```'), [('code', 'codice', 'x = 1')])

    def test_unclosed_fence_is_preserved(self):
        text = 'Risposta\n```python\nx = 1'
        self.assertEqual(split_fenced(text), [('text', '', text)])

    def test_inline_backticks_are_plain_text(self):
        text = 'Usa `print()` qui.'
        self.assertEqual(split_fenced(text), [('text', '', text)])

    def test_more_than_limit_remains_visible(self):
        text = ''.join(f'```python\n{i}\n```\n' for i in range(4))
        parts = split_fenced(text, max_blocks=2)
        self.assertEqual(sum(p[0] == 'code' for p in parts), 2)
        self.assertIn('```python\n2', parts[-1][2])

    def test_oversized_code_is_preserved_as_text(self):
        text = '```txt\n12345\n```'
        self.assertEqual(split_fenced(text, max_code_chars=4), [('text', '', text)])

    def test_non_string_is_rejected(self):
        with self.assertRaises(TypeError):
            split_fenced(None)


if __name__ == '__main__':
    unittest.main()
