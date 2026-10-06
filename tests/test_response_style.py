import unittest

from core.response_style import response_profile


class ResponseStyleTests(unittest.TestCase):
    def test_profiles_have_increasing_limits_and_matching_instructions(self):
        brief = response_profile('Breve')
        normal = response_profile('Normale')
        detailed = response_profile('Dettagliata')
        self.assertLess(brief[0], normal[0])
        self.assertLess(normal[0], detailed[0])
        self.assertIn('80 parole', brief[1])
        self.assertIn('completa', detailed[1])

    def test_study_normal_keeps_larger_budget(self):
        self.assertEqual(response_profile('Normale', 'Studio')[0], 900)
        self.assertEqual(response_profile('Normale', 'Chat')[0], 600)

    def test_unknown_profile_falls_back_to_brief(self):
        self.assertEqual(response_profile('sconosciuto'), response_profile('Breve'))


if __name__ == '__main__':
    unittest.main()
