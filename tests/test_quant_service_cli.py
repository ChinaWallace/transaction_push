"""Mock CLI service routing without settings files, network or real processes."""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class QuantServiceCliTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root=Path(directory.name)
        service=types.ModuleType('app.quant.service')
        service.OUTPUT=self.root/'output'
        service.atomic_json=Mock()
        service.read=lambda path: json.loads(path.read_text()) if path.exists() else {}
        settings=types.SimpleNamespace(quant_port=8765,quant_observation_seconds=60,
            quant_refresh_seconds=300,public_status=lambda:{'worker_enabled':True})
        config=types.ModuleType('app.core.runtime_config')
        config.get_runtime_settings=Mock(return_value=settings)
        path=Path(__file__).resolve().parents[1]/'scripts/quant_service.py'
        spec=importlib.util.spec_from_file_location('isolated_quant_service_cli',path)
        self.cli=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'app.quant.service':service,'app.core.runtime_config':config}):
            spec.loader.exec_module(self.cli)
        self.pid=self.cli.PID
        self.atomic_json=service.atomic_json
        self.run=patch.object(self.cli.subprocess,'run',return_value=types.SimpleNamespace(returncode=0)).start()
        self.addCleanup(patch.stopall)
        self.popen=patch.object(self.cli.subprocess,'Popen').start()
        self.call=patch.object(self.cli.subprocess,'call').start()
        self.kill=patch.object(self.cli.os,'kill').start()

    def metadata(self,research_only):
        self.pid.parent.mkdir(parents=True,exist_ok=True)
        self.pid.write_text(json.dumps({'pid':1234,'port':8765,'research_only':research_only}))

    def execute(self,command,pid):
        output=io.StringIO()
        with patch.object(self.cli,'owned_pid',return_value=pid), \
             patch.object(sys,'argv',['quant_service.py',command]),contextlib.redirect_stdout(output):
            self.cli.main()
        return output.getvalue()

    def test_start_all_routes_both_commands_for_running_paper_mode(self):
        self.metadata(False)
        self.execute('start-all',1234)
        self.assertEqual([c.args[0][2] for c in self.run.call_args_list],['start','forward-start'])
        self.popen.assert_not_called()
        self.kill.assert_not_called()

    def test_start_all_rejects_active_research_viewer_before_launching_anything(self):
        self.metadata(True)
        previous=self.pid.read_bytes()
        with self.assertRaisesRegex(SystemExit,'模式冲突.*quant.sh restart.*quant.sh start-all'):
            self.execute('start-all',1234)
        self.run.assert_not_called()
        self.popen.assert_not_called()
        self.call.assert_not_called()
        self.kill.assert_not_called()
        self.atomic_json.assert_not_called()
        self.assertEqual(self.pid.read_bytes(),previous)

    def test_stale_research_metadata_does_not_block_normal_start_all(self):
        self.metadata(True)
        self.execute('start-all',None)
        self.assertEqual([c.args[0][2] for c in self.run.call_args_list],['start','forward-start'])

    def test_readonly_status_does_not_present_old_runtime_as_running(self):
        self.metadata(True)
        runtime=types.ModuleType('app.quant.runtime')
        runtime.runtime_status=Mock(return_value={'state':'running','automatic':True,'cycles_completed':999})
        with patch.dict(sys.modules,{'app.quant.runtime':runtime}):
            status=json.loads(self.execute('status',1234))
        self.assertTrue(status['process_running'])
        self.assertTrue(status['research_only'])
        self.assertEqual(status['mode'],'research_only')
        self.assertEqual(status['runtime']['state'],'research_only')
        self.assertFalse(status['runtime']['automatic'])
        self.assertFalse(status['runtime']['configuration']['worker_enabled'])
        self.assertNotIn('cycles_completed',status['runtime'])
        runtime.runtime_status.assert_not_called()
        self.run.assert_not_called()
        self.popen.assert_not_called()
        self.kill.assert_not_called()

    def test_paper_status_preserves_runtime_status(self):
        self.metadata(False)
        runtime=types.ModuleType('app.quant.runtime')
        runtime.runtime_status=Mock(return_value={'state':'running','automatic':True,'cycles_completed':3})
        with patch.dict(sys.modules,{'app.quant.runtime':runtime}):
            status=json.loads(self.execute('status',1234))
        self.assertEqual(status['mode'],'paper')
        self.assertFalse(status['research_only'])
        self.assertTrue(status['runtime']['automatic'])
        self.assertEqual(status['runtime']['cycles_completed'],3)
        runtime.runtime_status.assert_called_once_with()


if __name__=='__main__':
    unittest.main()
