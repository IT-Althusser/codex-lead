"""仅测试调度状态机与消息传递；不连接桌面、不执行项目命令。"""
import argparse
from collections import deque
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('desktop', Path(__file__).with_name('desktop.py'))
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)
RealRpc = desktop.Rpc
real_desktop_evidence = desktop.desktop_evidence
TMP_ROOT = None


class FakeRpc:
    calls = []
    fail_start = False
    wait_status = 'completed'
    thread_turns = []
    project = ''

    def __init__(self, url, run=None, thread=None):
        self.thread = thread

    def call(self, method, params):
        self.calls.append((method, params))
        if method == 'thread/start':
            return {'thread': {'id': 'task-thread'}}
        if method == 'turn/start':
            if self.fail_start:
                raise ConnectionError('lost response')
            return {'turn': {'id': 'task-turn'}}
        return {}

    def read_thread(self):
        return {'id': self.thread, 'cwd': self.project, 'turns': self.thread_turns}

    def wait(self, turn_id, seconds):
        return {'id': turn_id, 'status': self.wait_status,
                'items': [{'type': 'agentMessage', 'phase': 'final_answer', 'text': '真实测试结果'}]}

    def close(self):
        pass


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TMP_ROOT)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        self.prompt = self.root / 'prompt.md'
        self.prompt.write_text('请完成已确认的修改；暂不提交。', encoding='utf-8')
        self.args = SimpleNamespace(task=str(self.root / 'task'), project=str(self.project),
                                    prompt=str(self.prompt), mode='workspace-write',
                                    url='ws://127.0.0.1:18765', wait=5)
        FakeRpc.calls = []
        FakeRpc.fail_start = False
        FakeRpc.wait_status = 'completed'
        FakeRpc.thread_turns = []
        FakeRpc.project = str(self.project)
        self.rpc = patch.object(desktop, 'Rpc', FakeRpc)
        self.evidence = patch.object(desktop, 'desktop_evidence', return_value={'desktopPid': 123})
        self.rpc.start()
        self.evidence.start()

    def tearDown(self):
        self.rpc.stop()
        self.evidence.stop()
        self.tmp.cleanup()

    def manifest(self):
        return json.loads((Path(self.args.task) / 'task.json').read_text(encoding='utf-8'))

    def test_new_session_same_connection_and_clean_prompt(self):
        desktop.send(self.args)
        self.assertEqual([c[0] for c in FakeRpc.calls], ['thread/start', 'turn/start'])
        sent = FakeRpc.calls[-1][1]['input'][0]['text']
        self.assertEqual(sent, self.prompt.read_text(encoding='utf-8'))
        self.assertNotIn('desktopPid', sent)
        self.assertEqual(self.manifest()['phase'], 'completed')
        self.assertFalse((Path(self.args.task) / 'dispatch.lock').exists())

    def test_followup_uses_exact_thread_and_new_run(self):
        desktop.send(self.args)
        first = self.manifest()['run']
        FakeRpc.calls = []
        desktop.send(self.args)
        self.assertEqual([c[0] for c in FakeRpc.calls], ['thread/resume', 'turn/start'])
        self.assertEqual(FakeRpc.calls[0][1], {'threadId': 'task-thread'})
        self.assertNotEqual(self.manifest()['run'], first)
        self.assertTrue((Path(first) / 'result.json').exists())

    def test_running_turn_prevents_duplicate(self):
        desktop.send(self.args)
        FakeRpc.thread_turns = [{'id': 'other-turn', 'status': 'inProgress'}]
        FakeRpc.calls = []
        with self.assertRaisesRegex(RuntimeError, '运行中'):
            desktop.send(self.args)
        self.assertEqual(FakeRpc.calls, [])

    def test_lost_start_response_marks_unknown_no_resubmit(self):
        FakeRpc.fail_start = True
        with self.assertRaises(ConnectionError):
            desktop.send(self.args)
        self.assertEqual(self.manifest()['phase'], 'unknown')
        self.assertNotIn('turnId', self.manifest())
        FakeRpc.fail_start = False
        FakeRpc.calls = []
        with self.assertRaisesRegex(RuntimeError, '先recover'):
            desktop.send(self.args)
        self.assertEqual(FakeRpc.calls, [])

    def test_failed_turn_not_success(self):
        FakeRpc.wait_status = 'failed'
        with self.assertRaisesRegex(RuntimeError, '未正常完成'):
            desktop.send(self.args)
        self.assertEqual(self.manifest()['phase'], 'failed')

    def test_mode_change_not_implicit(self):
        desktop.send(self.args)
        self.args.mode = 'read-only'
        with self.assertRaisesRegex(RuntimeError, '不隐式切换'):
            desktop.send(self.args)

    def test_desktop_missing_sends_nothing(self):
        with patch.object(desktop, 'desktop_evidence', side_effect=RuntimeError('not connected')):
            with self.assertRaises(RuntimeError):
                desktop.send(self.args)
        self.assertEqual(FakeRpc.calls, [])

    def test_wrong_project_thread_blocked(self):
        desktop.send(self.args)
        FakeRpc.project = str(self.root)
        with self.assertRaisesRegex(RuntimeError, '目录不符'):
            desktop.send(self.args)

    def test_recovery_does_not_send_turn(self):
        desktop.send(self.args)
        manifest = self.manifest()
        manifest['phase'] = 'unknown'
        desktop.write_json(Path(self.args.task) / 'task.json', manifest)
        FakeRpc.thread_turns = [{'id': 'task-turn', 'status': 'interrupted', 'items': []}]
        FakeRpc.calls = []
        desktop.recover(self.args)
        self.assertEqual(self.manifest()['phase'], 'interrupted')
        self.assertEqual(FakeRpc.calls, [])

    def test_lock_blocks_concurrent_dispatch(self):
        task = Path(self.args.task)
        task.mkdir()
        (task / 'dispatch.lock').write_text('999', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            desktop.send(self.args)
        self.assertEqual(FakeRpc.calls, [])

    def test_reject_nonlocal_url(self):
        for url in ('ws://example.com:18765', 'ws://user:pass@127.0.0.1:18765',
                    'ws://127.0.0.1:18765/?token=secret', 'wss://127.0.0.1:18765'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                desktop.local_url(url)

    def test_approval_only_single_explicit_decision(self):
        event = {'id': 0, 'method': 'item/commandExecution/requestApproval',
                 'params': {'threadId': 't', 'turnId': 'turn', 'command': 'git status'}}
        digest = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
        answer = self.root / ('decision-' + digest[:16] + '.json')
        desktop.write_json(answer, {'digest': digest, 'threadId': 't',
                                   'source': 'explicit-user-answer', 'decision': 'decline'})
        rpc = object.__new__(RealRpc)
        rpc.run = self.root
        rpc.thread = 't'
        sent = []
        rpc.ws = SimpleNamespace(recv=lambda **kw: json.dumps(event), send=sent.append)
        rpc.receive(1)
        self.assertEqual(json.loads(sent[0])['result']['decision'], 'decline')
        desktop.write_json(answer, {'digest': digest, 'threadId': 't',
                                   'source': 'explicit-user-answer', 'decision': 'acceptForSession'})
        with self.assertRaisesRegex(RuntimeError, '不自动放行'):
            rpc.receive(1)

    def test_desktop_child_connection_is_verified(self):
        data = {'processes': [
            {'ProcessId': 10, 'ParentProcessId': 1, 'Name': 'ChatGPT.exe',
             'ExecutablePath': 'C:/apps/OpenAI.Codex/app/ChatGPT.exe'},
            {'ProcessId': 11, 'ParentProcessId': 10, 'Name': 'network.exe'}],
            'connections': [{'OwningProcess': 11}]}
        with patch.object(desktop.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(data))):
            found = real_desktop_evidence('ws://127.0.0.1:18765')
        self.assertEqual(found['desktopPid'], 10)
        self.assertEqual(found['connectionPid'], 11)

    def test_backend_connection_is_not_desktop(self):
        data = {'processes': [{'ProcessId': 11, 'ParentProcessId': 1, 'Name': 'codex.exe',
                              'ExecutablePath': 'C:/bin/codex.exe'}],
                'connections': [{'OwningProcess': 11}]}
        with patch.object(desktop.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(data))):
            with self.assertRaisesRegex(RuntimeError, '未核实'):
                real_desktop_evidence('ws://127.0.0.1:18765')

    def test_wait_ignores_other_turn_completion(self):
        rpc = object.__new__(RealRpc)
        rpc.run = self.root
        rpc.thread = 't'
        rpc.events = deque([
            {'method': 'turn/completed', 'params': {'threadId': 'other',
                                                  'turn': {'id': 'wanted', 'status': 'completed'}}},
            {'method': 'turn/completed', 'params': {'threadId': 't',
                                                  'turn': {'id': 'different', 'status': 'completed'}}},
            {'method': 'turn/completed', 'params': {'threadId': 't',
                                                  'turn': {'id': 'wanted', 'status': 'failed'}}}])
        result = rpc.wait('wanted', 5)
        self.assertEqual(result['status'], 'failed')

    def test_watcher_reports_dispatch_error(self):
        desktop.write_json(self.root / 'dispatch-error.json', {'error': 'socket closed'})
        with patch('builtins.print') as output:
            desktop.watch(SimpleNamespace(run=str(self.root), seconds=2))
        self.assertIn('dispatch-error.json', output.call_args.args[0])

    def test_lost_turn_start_cannot_recover_as_previous_turn(self):
        desktop.send(self.args)
        FakeRpc.fail_start = True
        with self.assertRaises(ConnectionError):
            desktop.send(self.args)
        FakeRpc.thread_turns = [{'id': 'task-turn', 'status': 'completed', 'items': []}]
        desktop.recover(self.args)
        self.assertEqual(self.manifest()['phase'], 'unknown')
        self.assertNotIn('turnId', self.manifest())

    def test_unknown_approval_fail_closed(self):
        rpc = object.__new__(RealRpc)
        rpc.run = self.root
        rpc.thread = 't'
        sent = []
        rpc.ws = SimpleNamespace(recv=lambda **kw: json.dumps({'id': 5, 'method': 'unknown'}),
                                 send=sent.append)
        with self.assertRaises(RuntimeError):
            rpc.receive(1)
        self.assertIn('error', json.loads(sent[0]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tmp-root', required=True)
    args, rest = parser.parse_known_args()
    TMP_ROOT = args.tmp_root
    Path(TMP_ROOT).mkdir(parents=True, exist_ok=True)
    unittest.main(argv=['test_desktop.py'] + rest)
