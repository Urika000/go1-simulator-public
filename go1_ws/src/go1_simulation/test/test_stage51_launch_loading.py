"""Stage 5.1: real launch loading checks, not just py_compile.

Run with: python3 go1_ws/src/go1_simulation/test/test_stage51_launch_loading.py
Within Docker after the workspace is sourced, also executes `ros2 launch --show-args`.
"""
import ast
from pathlib import Path
import shutil
import subprocess
import unittest

SRC = Path(__file__).resolve().parents[2]
SIM_LAUNCH = SRC / 'go1_simulation' / 'launch'
ALL_LAUNCHES = tuple(sorted(SRC.glob('*/launch/*.launch.py')))
ACTIVE_SIM_LAUNCHES = ('scenario.launch.py', 'go1_simulation.launch.py',
                       'mujoco.launch.py', 'gazebo.launch.py')


class LaunchLoadingTests(unittest.TestCase):
    def test_all_launch_files_parse(self):
        self.assertTrue(ALL_LAUNCHES)
        for launch in ALL_LAUNCHES:
            with self.subTest(launch=str(launch)):
                ast.parse(launch.read_text(encoding='utf-8'), filename=str(launch))

    def test_no_stray_module_level_name_expressions(self):
        # `COURSE_` is valid Python syntax, but raises NameError at module import.
        for launch in ALL_LAUNCHES:
            with self.subTest(launch=str(launch)):
                module = ast.parse(launch.read_text(encoding='utf-8'))
                stray = [(node.lineno, node.value.id) for node in module.body
                         if isinstance(node, ast.Expr) and isinstance(node.value, ast.Name)]
                self.assertEqual(stray, [], f'Unexpected bare names in {launch}: {stray}')

    @unittest.skipUnless(shutil.which('ros2'), 'ROS 2 not installed: run this check in Docker')
    def test_active_launch_files_load_in_ros2(self):
        # --show-args imports each launch description without starting simulation.
        for filename in ACTIVE_SIM_LAUNCHES:
            with self.subTest(launch=filename):
                result = subprocess.run(
                    ['ros2', 'launch', 'go1_simulation', filename, '--show-args'],
                    text=True, capture_output=True, timeout=35, check=False)
                self.assertEqual(result.returncode, 0,
                                 f'{filename} failed to load:\n{result.stdout}\n{result.stderr}')

    def test_no_removed_launch_dependencies(self):
        scenario = (SIM_LAUNCH / 'scenario.launch.py').read_text(encoding='utf-8')
        self.assertIn('COURSE_WIDTHS', scenario)
        self.assertNotIn("LaunchConfiguration('control_mode')", scenario)
        self.assertNotIn("scenario == 'maze'", scenario)
        for filename in ACTIVE_SIM_LAUNCHES:
            self.assertTrue((SIM_LAUNCH / filename).is_file(), filename)


if __name__ == '__main__':
    unittest.main(verbosity=2)
