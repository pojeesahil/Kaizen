import unittest
import tempfile
from pathlib import Path

from cag.cag import CAG, CodebaseCache, indexWorkspace, getContext, updateWorkspaceFile, getCAG
import rag.rag as legacy_rag

class TestCAGSuite(unittest.TestCase):

    def setUp(self):
        self.tmpDir = tempfile.TemporaryDirectory()
        self.workPath = Path(self.tmpDir.name)

        (self.workPath / "app.py").write_text("def run():\n    return 42\n", encoding="utf-8")
        (self.workPath / "utils.js").write_text("function add(a, b) { return a + b; }\n", encoding="utf-8")
        (self.workPath / "style.css").write_text("body { margin: 0; }\n", encoding="utf-8")

        sub = self.workPath / "sub"
        sub.mkdir()
        (sub / "nested.py").write_text("x = 100\n", encoding="utf-8")

    def tearDown(self):
        self.tmpDir.cleanup()

    def testCagPreloadAndContext(self):
        cag = CAG(workDir=str(self.workPath))
        count = cag.preload()
        self.assertEqual(count, 4)

        context = cag.getContext("test query")
        self.assertIn("--- app.py ---", context)
        self.assertIn("def run():", context)
        self.assertIn("--- utils.js ---", context)
        self.assertIn("function add(a, b)", context)
        self.assertIn("--- style.css ---", context)
        self.assertIn("--- sub/nested.py ---", context)
        self.assertIn("x = 100", context)

    def testCagIncrementalUpdate(self):
        cag = CAG(workDir=str(self.workPath))
        cag.preload()

        appFile = self.workPath / "app.py"
        appFile.write_text("def run():\n    return 'updated'\n", encoding="utf-8")

        cag.updateFile(str(appFile))
        context = cag.getContext()
        self.assertIn("return 'updated'", context)

        utilsFile = self.workPath / "utils.js"
        utilsFile.unlink()
        cag.updateFile(str(utilsFile))

        contextAfterDel = cag.getContext()
        self.assertNotIn("utils.js", contextAfterDel)

    def testLegacyRagCompatibility(self):
        legacy_rag.indexWorkspace(str(self.workPath))
        ctx = legacy_rag.getContext("instruction")
        self.assertIn("--- app.py ---", ctx)
        self.assertIn("def run():", ctx)

if __name__ == "__main__":
    unittest.main()
