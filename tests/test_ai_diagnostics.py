"""No external API calls. Regression tests for missing key, live output, and failures."""
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from disruption_iq import ai

DISRUPTION = {'kind':'CARRIER_DELAY', 'title':'Container Ship X', 'detail':'Revised ETA', 'severity':'HIGH'}
TRACE = {'exposure':272000, 'orders':[{'order_no':'ORD-90243', 'score':90,'short_units':67,'sla_due':'2026-11-04'}]}
ORDER = {'order_no':'ORD-90243','risk':90,'short_units':67,'value':200000,'priority':'CRITICAL','sla_due':'2026-11-04'}
OPTIONS = [{'kind':'REORDER','qty':67,'eta_days':5,'estimate_cost':3329,'sla_note':'Projected after SLA','meets_sla':False}]


def fake_settings(name, default=''):
    return {'OPENAI_API_KEY':'sk-test-key','OPENAI_MODEL':'gpt-4.1-mini'}.get(name, default)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()


class AIDiagnosticsTests(unittest.TestCase):
    def test_no_key_never_calls_network(self):
        with patch.object(ai,'_setting',return_value=''), patch.object(ai.urllib.request,'urlopen') as http:
            text, status=ai.summarize_with_status(DISRUPTION, TRACE, ORDER, OPTIONS)
        self.assertIn('deterministic fallback',text)
        self.assertIn('NO API KEY',status)
        http.assert_not_called()

    def test_configured_key_is_not_labeled_connected_until_tested(self):
        with patch.object(ai,'_setting',side_effect=fake_settings):
            self.assertIn('NOT YET VERIFIED',ai.availability())

    def test_live_response_is_truthfully_labeled(self):
        payload={'choices':[{'message':{'content':'DISRUPTION: Ship delayed.\nRECOVERY: Reorder if approved.'}}]}
        response=FakeResponse(json.dumps(payload).encode())
        with patch.object(ai,'_setting',side_effect=fake_settings), patch.object(ai.urllib.request,'urlopen',return_value=response):
            content,status=ai.summarize_with_status(DISRUPTION, TRACE, ORDER, OPTIONS)
        self.assertIn('AI-generated narrative',content)
        self.assertEqual(status,'LIVE AI · CONNECTED')
        self.assertNotIn('sk-test-key',content)

    def test_invalid_key(self):
        err=urllib.error.HTTPError(ai.API_URL,401,'Unauthorized',{},io.BytesIO(b'{"error":{"code":"invalid_api_key"}}'))
        with patch.object(ai,'_setting',side_effect=fake_settings), patch.object(ai.urllib.request,'urlopen',side_effect=err):
            content,status=ai.summarize_with_status(DISRUPTION, TRACE, ORDER, OPTIONS)
        self.assertIn('HTTP 401',content)
        self.assertIn('deterministic fallback',content)
        self.assertEqual(status,'AI OFFLINE · REQUEST FAILED')

    def test_insufficient_quota(self):
        body=b'{"error":{"code":"insufficient_quota","message":"You exceeded your current quota"}}'
        err=urllib.error.HTTPError(ai.API_URL,429,'Too Many Requests',{},io.BytesIO(body))
        with patch.object(ai,'_setting',side_effect=fake_settings), patch.object(ai.urllib.request,'urlopen',side_effect=err):
            content,status=ai.summarize_with_status(DISRUPTION, TRACE, ORDER, OPTIONS)
        self.assertIn('billing limit',content)
        self.assertEqual(status,'AI OFFLINE · REQUEST FAILED')

    def test_model_unavailable(self):
        err=urllib.error.HTTPError(ai.API_URL,404,'Not Found',{},io.BytesIO(b'{"error":{"code":"model_not_found"}}'))
        with patch.object(ai,'_setting',side_effect=fake_settings), patch.object(ai.urllib.request,'urlopen',side_effect=err):
            content,status=ai.summarize_with_status(DISRUPTION, TRACE, ORDER, OPTIONS)
        self.assertIn('OPENAI_MODEL',content)
        self.assertEqual(status,'AI OFFLINE · REQUEST FAILED')

    def test_network_failure(self):
        err=urllib.error.URLError('No route to host')
        with patch.object(ai,'_setting',side_effect=fake_settings), patch.object(ai.urllib.request,'urlopen',side_effect=err):
            content,status=ai.summarize_with_status(DISRUPTION, TRACE, ORDER, OPTIONS)
        self.assertIn('Network error',content)
        self.assertNotIn('No route to host',content)
        self.assertEqual(status,'AI OFFLINE · REQUEST FAILED')

    def test_backcompat_summarize(self):
        with patch.object(ai,'_setting',return_value=''):
            out=ai.summarize(DISRUPTION, TRACE, ORDER, OPTIONS)
        self.assertIsInstance(out,str)
        self.assertIn('ORD-90243',out)

    def test_local_env_reads_config_without_dependency(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as d:
            project=Path(d)
            (project / '.env').write_text('OPENAI_API_KEY="sk-test-local"\nOPENAI_MODEL=gpt-4.1-mini\n',encoding='utf-8')
            original=ai.Path
            class FakePath:
                def __call__(self,*args,**kwargs):
                    return original(*args,**kwargs)
                def __getattr__(self, k):
                    return getattr(original,k)
            # local env parsing exercised by substituting only module __file__
            with patch.object(ai,'__file__',str(project/'disruption_iq'/'ai.py')):
                self.assertEqual(ai._local_env()['OPENAI_API_KEY'],'sk-test-local')


if __name__ == '__main__':
    unittest.main()
