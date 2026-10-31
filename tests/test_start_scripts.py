"""启动脚本的不变量：构建失败绝不能阻止服务启动。

这条测试是一次真实事故的绊线。`start.ps1` 顶部有 `$ErrorActionPreference = "Stop"`，
而 npm 把警告写到 stderr；PowerShell 会把 native 命令的 stderr 升级成终止性错误，
于是脚本在"启动服务"那一行之前就死了。症状是整个应用打不开——看起来像数据全丢，
实际上服务从来没起来。文本断言比较笨，但这类错误的代价远高于测试的丑陋程度。
"""
import re
import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401,E402

ROOT = _bootstrap.ROOT
PS1 = ROOT / "scripts" / "start.ps1"
SH = ROOT / "scripts" / "start.sh"


class PowerShellStartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PS1.read_text(encoding="utf-8-sig")
        cls.raw = PS1.read_bytes()

    def test_file_keeps_utf8_bom(self):
        """没有 BOM 时 PowerShell 会按 ANSI/GBK 解码中文注释，直接语法错。"""
        self.assertTrue(self.raw.startswith(b"\xef\xbb\xbf"))

    def test_npm_runs_with_errors_downgraded(self):
        """npm 调用必须处在 ErrorActionPreference=Continue 的区间内。"""
        cont = self.text.index('$ErrorActionPreference = "Continue"')
        npm_calls = [m.start() for m in re.finditer(r'&\s*npm\s', self.text)]
        self.assertTrue(npm_calls, "脚本里应当有 npm 调用")
        self.assertTrue(all(pos > cont for pos in npm_calls),
                        "存在不受 Continue 保护的 npm 调用，构建失败会终止脚本")

    def test_error_preference_is_restored(self):
        self.assertIn("finally {", self.text)
        finally_block = self.text[self.text.index("finally {"):]
        self.assertIn('$ErrorActionPreference = "Stop"', finally_block)
        self.assertIn("Pop-Location", finally_block)

    def test_server_start_comes_after_the_build_block(self):
        """服务启动必须在构建之后、且不被构建结果守卫包住。"""
        build = self.text.index("Rebuilding frontend")
        start = self.text.index("backend\\run.py")
        self.assertGreater(start, build)

    def test_server_start_is_the_last_statement(self):
        lines = [l.strip() for l in self.text.splitlines() if l.strip() and not l.strip().startswith("#")]
        self.assertTrue(lines[-1].endswith("backend\\run.py"),
                        f"最后一条语句应当是启动服务，实际是：{lines[-1]}")

    def test_build_failure_path_tells_the_user_the_backend_still_works(self):
        self.assertIn("NOT rebuilt", self.text)
        self.assertIn("start normally regardless", self.text)

    def test_nobuild_switch_exists(self):
        self.assertIn("[switch]$NoBuild", self.text)

    def test_port_is_not_hijacked(self):
        """-Port 未指定时必须沿用已有的 REVIEW_PORT，不能无条件改成默认值。"""
        self.assertIn("[int]$Port = 0", self.text)
        self.assertIn("$env:REVIEW_PORT", self.text)
        resolve = self.text.index("if ($Port -le 0)")
        assign = self.text.index("$env:REVIEW_PORT = $Port")
        self.assertLess(resolve, assign, "必须先解析端口再写回环境变量")

    def test_default_port_matches_the_backend_default(self):
        """脚本兜底端口必须和 run.py 的兜底端口一致，否则同一个项目有两个"默认端口"。"""
        run_py = (ROOT / "backend" / "run.py").read_text(encoding="utf-8")
        # run.py 的 REVIEW_PORT 默认值是 "0"（= 自动挑端口），真正的兜底端口是候选列表的第一个。
        # 旧版测试读的是 REVIEW_PORT 默认值，run.py 改成自动选端口后这条测试就一直在误报。
        m = re.search(r"CANDIDATES\s*=\s*\[\s*(\d+)", run_py)
        self.assertIsNotNone(m, "run.py 里没找到 CANDIDATES 候选端口列表")
        default = m.group(1)
        self.assertRegex(self.text, r"else\s*\{\s*" + default + r"\s*\}",
                         f"start.ps1 的兜底端口应当是 {default}")


class ShellStartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SH.read_text(encoding="utf-8")

    def test_build_failure_does_not_abort(self):
        """set -e 下必须显式接住构建失败。"""
        self.assertIn("set -e", self.text)
        self.assertTrue("if (cd frontend" in self.text,
                        "npm 构建应放在 if 判断里，失败不致命")
        self.assertIn("不受影响", self.text)

    def test_exec_server_is_last(self):
        lines = [l.strip() for l in self.text.splitlines() if l.strip() and not l.strip().startswith("#")]
        self.assertTrue(lines[-1].startswith("exec"), lines[-1])

    def test_find_failure_cannot_abort(self):
        self.assertIn("|| true", self.text)


if __name__ == "__main__":
    unittest.main()
