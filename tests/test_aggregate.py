import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from aggregate import aggregate_category, normalize_source_line, parse_readme, run, source_files, validate_rule


class ReadmeTests(unittest.TestCase):
    def test_category_tables_and_nested_directories(self):
        source = """## 分类
|🌏Global|  |  |
| ---- | ---- | ---- |
|[A](https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Surge/A)|[B](https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Surge/Game/Assassin'sCreed)|
|[A](https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Surge/A)|
|📵Advertising|  |  |
| ---- | ---- | ---- |
|[Ads](https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Surge/Ads)|
## Other
"""
        self.assertEqual(parse_readme(source), {"Global": ["A", "Game/Assassin'sCreed"], "Advertising": ["Ads"]})

    def test_missing_and_traversal_fail(self):
        with self.assertRaises(ValueError):
            parse_readme("## 分类\n|🌏Global|  |\n")
        with self.assertRaises(ValueError):
            parse_readme("## 分类\n|🌏Global|  |\n|[x](https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Surge/%2e%2e/x)|")


class RuleTests(unittest.TestCase):
    def test_domain_set_conversion(self):
        self.assertEqual(normalize_source_line(".example.com", "A_Domain.list"), ("DOMAIN-SUFFIX,example.com", True))
        self.assertEqual(normalize_source_line("example.com", "A_Domain.list"), ("DOMAIN,example.com", True))
        self.assertEqual(normalize_source_line("DOMAIN,example.com", "A.list"), ("DOMAIN,example.com", False))
        with self.assertRaises(ValueError):
            normalize_source_line("*.example.com", "A_Domain.list")

    def test_rules_parameters_and_invalid_rules(self):
        for line in ["DOMAIN,example.com", "IP-CIDR,1.2.3.0/24", "IP-CIDR,1.2.3.0/24,no-resolve", "IP-ASN,13335,no-resolve", "AND,((USER-AGENT,Frodo*),(DOMAIN,119.29.29.29))"]:
            validate_rule(line)
        for line in ["garbage", "FINAL,DIRECT", "IP-CIDR,not-an-ip", "IP-CIDR,1.2.3.0/24,unknown", "DOMAIN,", "AND,((BAD,value),(DOMAIN,example.com))", "AND,((DOMAIN,example.com))"]:
            with self.subTest(line=line), self.assertRaises(ValueError):
                validate_rule(line)

    def test_aggregate_dedup_preserves_first_order_and_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "A").mkdir()
            (root / "A" / "A.list").write_text("# comment\nDOMAIN,example.com\nIP-CIDR,1.2.3.0/24,no-resolve\n", encoding="utf-8")
            (root / "A" / "A_Domain.list").write_text("example.com\n.example.org\n", encoding="utf-8")
            out = root / "out.list"
            stats = aggregate_category(root, ["A"], out, {"branch": "main", "commit": "abc"})
            lines = [line for line in out.read_text().splitlines() if not line.startswith("#")]
            self.assertEqual(lines, ["DOMAIN,example.com", "IP-CIDR,1.2.3.0/24,no-resolve", "DOMAIN-SUFFIX,example.org"])
            self.assertEqual((stats["before"], stats["duplicates"], stats["after"], stats["domain_set_converted"]), (4, 1, 3, 2))
            with self.assertRaises(FileNotFoundError):
                source_files(root, ["missing"])

    def test_nested_directory_file_is_read_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "A" / "B").mkdir(parents=True)
            (root / "A" / "B" / "x.list").write_text("DOMAIN,example.com\n")
            self.assertEqual(len(source_files(root, ["A", "A/B"])), 1)


class EndToEndTests(unittest.TestCase):
    def test_missing_source_strict_failure_and_diagnostic_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "upstream"
            surge = repo / "rule" / "Surge"
            (surge / "Present").mkdir(parents=True)
            (surge / "README.md").write_text(
                "## 分类\n|🌏Global|  |\n|---|---|\n"
                "|[A](https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Surge/Present)"
                "|[B](https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Surge/Missing)|\n",
                encoding="utf-8")
            (surge / "Present" / "Present.list").write_text("DOMAIN,example.com\n", encoding="utf-8")
            def git(*args):
                return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
            git("init", "-b", "main")
            git("config", "user.email", "test@example.invalid")
            git("config", "user.name", "test")
            git("add", ".")
            git("-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-m", "fixture")
            output = root / "output"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "Missing"):
                run(repo, output)
            self.assertFalse((output / "generated").exists())
            report = run(repo, output, allow_missing=True)
            self.assertFalse(report["complete"])
            self.assertEqual(report["missing_directories"], {"Global": ["Missing"]})
            generated = output / "generated" / "surge" / "Global.list"
            self.assertIn("# INCOMPLETE: missing upstream directories: Missing", generated.read_text())
            old = generated.read_bytes()
            with self.assertRaises(ValueError):
                run(repo, output)
            self.assertEqual(generated.read_bytes(), old)
            extra = generated.parent / "unmanaged.txt"
            extra.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "未知文件"):
                run(repo, output, allow_missing=True)
            self.assertEqual(extra.read_text(), "keep")
            self.assertEqual(generated.read_bytes(), old)
            self.assertEqual(git("status", "--porcelain").stdout, b"")


if __name__ == "__main__":
    unittest.main()
