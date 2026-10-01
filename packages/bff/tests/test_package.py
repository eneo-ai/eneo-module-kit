import ast
import re
import unittest
from collections import Counter
from pathlib import Path

SOURCES = sorted((Path(__file__).parent.parent / "src" / "eneo_module_bff").glob("*.py"))


class PackageTests(unittest.TestCase):
    def test_the_package_imports_and_names_its_version(self) -> None:
        import eneo_module_bff

        self.assertRegex(eneo_module_bff.__version__, r"^0\.\d+\.\d+$")

    def test_no_module_defines_a_top_level_name_twice(self) -> None:
        # The second definition wins silently, so a constant copied into two places drifts apart.
        for path in SOURCES:
            names = Counter(
                target.id
                for node in ast.parse(path.read_text()).body
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else [])
                if isinstance(target, ast.Name)
            )
            with self.subTest(module=path.name):
                self.assertEqual([name for name, count in names.items() if count > 1], [])

    def test_the_package_names_no_organisation_and_no_product(self) -> None:
        # The kit is generic: the organisation and the product are a module's and a deployment's.
        for path in SOURCES:
            with self.subTest(module=path.name):
                self.assertEqual(re.findall(r"sundsvall|tal till text", path.read_text(), re.IGNORECASE), [])


if __name__ == "__main__":
    unittest.main()
