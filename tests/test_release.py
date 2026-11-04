import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prepare_release import classify


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.rules = {"OpenAI": ["DOMAIN-SUFFIX,openai.com", "DOMAIN,chat.com"],
                      "Anthropic": ["DOMAIN-SUFFIX,anthropic.com", "DOMAIN-SUFFIX,claude.ai"]}

    def test_scoped_domains_and_keywords(self):
        for line in ["DOMAIN,api.openai.com", "DOMAIN-SUFFIX,openai.com", "DOMAIN,chat.com"]:
            self.assertEqual(classify(line, self.rules), "OpenAI")
        self.assertEqual(classify("DOMAIN,api.anthropic.com", self.rules), "Anthropic")
        self.assertEqual(classify("DOMAIN-KEYWORD,claude", self.rules), "quarantine")
        for line in ["DOMAIN,notopenai.com", "DOMAIN,chatgptvideo.xyz", "DOMAIN,claudestudio.com", "DOMAIN-SUFFIX,datadoghq.com"]:
            self.assertIsNone(classify(line, self.rules))


if __name__ == "__main__":
    unittest.main()
