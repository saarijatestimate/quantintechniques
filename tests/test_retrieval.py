import unittest

from scripts.retrieval import retrieve_top_k, rewrite_query


class RetrievalTests(unittest.TestCase):
    def test_rewrite_query_expands_synonyms(self):
        rewritten = rewrite_query('refund issue', synonyms={'refund': ['money back', 'reimbursement']})
        self.assertIn('money back', rewritten.lower())

    def test_retrieve_top_k_filters_and_ranks(self):
        chunks = [
            {
                'id': 1,
                'source': 'support',
                'text': 'Customer requested a refund and reimbursement for the duplicate invoice.',
                'embedding': [1.0, 0.0, 0.0],
            },
            {
                'id': 2,
                'source': 'blog',
                'text': 'New product release notes for the sales team.',
                'embedding': [0.0, 1.0, 0.0],
            },
            {
                'id': 3,
                'source': 'support',
                'text': 'Customer asked about order tracking and shipping status.',
                'embedding': [0.8, 0.2, 0.0],
            },
        ]

        results = retrieve_top_k(
            chunks,
            query='refund',
            top_k=2,
            filters={'source': 'support'},
            query_rewrite=True,
            rerank=True,
            synonyms={'refund': ['money back', 'reimbursement']},
        )

        self.assertEqual(results[0]['id'], 1)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(item['source'] == 'support' for item in results))


if __name__ == '__main__':
    unittest.main()
