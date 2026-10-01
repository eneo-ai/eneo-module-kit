import unittest


class PackageTests(unittest.TestCase):
    def test_the_package_imports_and_names_its_version(self) -> None:
        import eneo_module_bff

        self.assertRegex(eneo_module_bff.__version__, r"^0\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
