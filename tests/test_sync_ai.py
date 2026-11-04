import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from sync_ai import parse_source, stage_outputs, write_outputs


OPENAI = b"# Core\nDOMAIN-SUFFIX,openai.com\nPROCESS-NAME,Codex\n# Network\nIP-CIDR,1.2.3.0/24,no-resolve\n# Third-Party\nDOMAIN-SUFFIX,sentry.io\n"
ANTHROPIC = b"# Core\nDOMAIN-SUFFIX,claude.ai\nPROCESS-NAME,Claude\n# Third-Party\nDOMAIN-SUFFIX,sentry.io\nDOMAIN-SUFFIX,chatbotclaude.com\n"


class SyncTests(unittest.TestCase):
    def fixture(self, root):
        for name in ("rules", "support", "inputs", "config", "reports"):
            (root / name).mkdir()
        base = b"# upstream\nDOMAIN-SUFFIX,openai.com\nDOMAIN,api.claude.ai\nDOMAIN-SUFFIX,chatbotclaude.com\nDOMAIN-SUFFIX,sentry.io\nDOMAIN-KEYWORD,openai\nIP-CIDR,1.2.3.0/24,no-resolve\nIP-CIDR,1.2.3.0/24\n"
        (root / "inputs/Global.unfiltered.list").write_bytes(base)
        (root / "config/global-baseline.json").write_text(json.dumps({"sha256": hashlib.sha256(base).hexdigest()}))
        (root / "config/ai_rules.json").write_text(json.dumps({"OpenAI": ["DOMAIN-SUFFIX,openai.com"], "Anthropic": ["DOMAIN-SUFFIX,claude.ai"]}))
        (root / "reports/release-report.json").write_text(json.dumps({"sha256": {}, "complete": False}))

    def test_preserves_upstream_bytes_and_shared_global(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            outputs = stage_outputs(root, "a" * 40, {"OpenAI": OPENAI, "Anthropic": ANTHROPIC})
            self.assertEqual(outputs[root / "rules/OpenAI.list"], OPENAI)
            self.assertEqual(outputs[root / "rules/Anthropic.list"], ANTHROPIC)
            priority = outputs[root / "support/Anthropic-Domains.list"].decode()
            self.assertIn("DOMAIN-SUFFIX,claude.ai", priority)
            self.assertIn("DOMAIN-SUFFIX,chatbotclaude.com", priority)
            self.assertNotIn("sentry.io", priority)
            self.assertNotIn("PROCESS-NAME", priority)
            global_data = outputs[root / "rules/Global.list"].decode()
            self.assertNotIn("DOMAIN-SUFFIX,openai.com", global_data)
            self.assertNotIn("DOMAIN,api.claude.ai", global_data)
            self.assertNotIn("DOMAIN-KEYWORD,openai", global_data)
            self.assertIn("DOMAIN-SUFFIX,sentry.io", global_data)
            self.assertNotIn("DOMAIN-SUFFIX,chatbotclaude.com", global_data)
            self.assertNotIn("IP-CIDR,1.2.3.0/24,no-resolve", global_data)
            self.assertIn("IP-CIDR,1.2.3.0/24\n", global_data)
            self.assertEqual(write_outputs(outputs), 6)
            self.assertEqual(write_outputs(outputs), 0)
            report = json.loads((root / "reports/ai-sync.json").read_text())
            self.assertEqual(report["shared_exact_rules"], ["DOMAIN-SUFFIX,sentry.io"])

    def test_invalid_input_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            with self.assertRaises(ValueError):
                stage_outputs(root, "a" * 40, {"OpenAI": OPENAI, "Anthropic": b"# Core\nBAD,rule\n"})
            self.assertEqual(list((root / "rules").iterdir()), [])
            with self.assertRaises(ValueError):
                parse_source(b"# Third-Party\nDOMAIN,example.org\n", "test")


if __name__ == "__main__":
    unittest.main()
