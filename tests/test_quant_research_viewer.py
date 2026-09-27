import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app.application import create_app
from app.core.runtime_config import RuntimeSettings


class ResearchViewerTests(unittest.IsolatedAsyncioTestCase):
    async def test_viewer_does_not_start_worker_and_rejects_mutations(self):
        with tempfile.TemporaryDirectory() as folder:
            settings=RuntimeSettings(_env_file=None,app_profile='quant',quant_output_dir=Path(folder),quant_worker_enabled=True)
            with patch('app.application.get_runtime_settings',return_value=settings), \
                 patch('app.quant.runtime.PaperWorker') as worker:
                app=create_app(research_only=True)
                async with app.router.lifespan_context(app):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost') as client:
                        for method,path in [('POST','/api/quant/paper/step'),('PUT','/api/quant/policy'),('DELETE','/anything')]:
                            response=await client.request(method,path,json={})
                            self.assertEqual(response.status_code,405)
                        with patch('app.quant.runtime.runtime_status',return_value={'state':'stopped','configuration':{'worker_enabled':True}}):
                            response=await client.get('/api/quant/runtime')
                        self.assertEqual(response.json()['state'],'research_only')
                        self.assertFalse(response.json()['automatic'])
                        self.assertFalse(response.json()['configuration']['worker_enabled'])
                worker.assert_not_called()
                self.assertFalse((Path(folder)/'paper.sqlite3').exists())

    async def test_legacy_profile_cannot_bypass_read_only_guard(self):
        settings=RuntimeSettings(_env_file=None,app_profile='legacy')
        with patch('app.application.get_runtime_settings',return_value=settings):
            with self.assertRaises(ValueError):create_app(research_only=True)
