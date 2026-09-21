import unittest

from scripts.prompt_builder import build_context_prompt


class PromptBuilderTests(unittest.TestCase):
    def test_prompt_includes_chunks_and_metadata(self):
        chunks = [
            {
                'id': 7,
                'source': 'policy.md',
                'text': 'Refunds are processed within 30 days.',
                'metadata': {'section': 'refunds'},
            }
        ]

        prompt = build_context_prompt('When do refunds arrive?', chunks)

        self.assertIn('Retrieved evidence', prompt)
        self.assertIn('policy.md', prompt)
        self.assertIn('Refunds are processed within 30 days.', prompt)
        self.assertIn('section=refunds', prompt)


if __name__ == '__main__':
    unittest.main()
