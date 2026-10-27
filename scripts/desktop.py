"""Codex桌面共享会话调度；项目内容仅来自UTF-8任务文件。"""
import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlparse

TERMINAL = {'completed', 'failed', 'interrupted'}
APPROVALS = {'item/commandExecution/requestApproval', 'item/fileChange/requestApproval'}


def write_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def local_url(value):
    u = urlparse(value)
    if (u.scheme != 'ws' or u.hostname != '127.0.0.1' or not u.port
            or u.username or u.password or u.query or u.fragment or u.path not in ('', '/')):
        raise ValueError('仅允许无凭据的 ws://127.0.0.1:端口')
    return value


def desktop_evidence(url):
    port = urlparse(local_url(url)).port
    script = (
        "$p=@(Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath);"
        f"$c=@(Get-NetTCPConnection -RemotePort {port} -State Established -ErrorAction SilentlyContinue | "
        "Where-Object {$_.RemoteAddress -eq '127.0.0.1'} | Select-Object OwningProcess);"
        "@{processes=$p;connections=$c}|ConvertTo-Json -Depth 4 -Compress"
    )
    out = subprocess.run(['powershell.exe', '-NoProfile', '-Command', script],
                         capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    processes = {p['ProcessId']: p for p in data['processes']}
    for connection in data['connections']:
        pid = connection['OwningProcess']
        seen = set()
        current = pid
        while current in processes and current not in seen:
            seen.add(current)
            p = processes[current]
            # codex.exe通常是后端，不能仅凭它有连接认定桌面已连。
            if (p['Name'].lower() in ('chatgpt.exe', 'codexdesktop.exe')
                    and 'codex' in (p.get('ExecutablePath') or '').lower()):
                return {'desktopPid': current, 'connectionPid': pid, 'url': url}
            current = p['ParentProcessId']
    raise RuntimeError('未核实Codex桌面进程到共享端口的实际连接；不发送项目任务')


def final_message(turn):
    messages = [i for i in turn.get('items', []) if i.get('type') == 'agentMessage']
    final = [i for i in messages if i.get('phase') == 'final_answer']
    return (final or messages)[-1].get('text') if messages else None


class Rpc:
    def __init__(self, url, run=None, thread=None):
        from websockets.sync.client import connect
        self.connection = connect(local_url(url), proxy=None, open_timeout=5,
                                  close_timeout=2, ping_interval=None,
                                  max_size=32 * 1024 * 1024)
        self.ws = self.connection.__enter__()
        self.run = run
        self.thread = thread
        self.sequence = 0
        self.events = deque()
        try:
            self.info = self.call('initialize', {
                'clientInfo': {'name': 'desktop_mentor', 'version': '1.0'},
                'capabilities': {'experimentalApi': True}})
            self.ws.send(json.dumps({'method': 'initialized', 'params': {}}))
        except BaseException:
            self.close()
            raise

    def close(self):
        self.connection.__exit__(None, None, None)

    def receive(self, timeout):
        event = json.loads(self.ws.recv(timeout=timeout))
        if 'id' in event and 'method' in event:
            if (self.run is None or event['method'] not in APPROVALS
                    or event.get('params', {}).get('threadId') != self.thread):
                self.ws.send(json.dumps({'id': event['id'], 'error': {
                    'code': -32601, 'message': 'Unsupported approval; no permission granted'}}))
                raise RuntimeError('遇到未支持/不属于本任务的审批，未授予权限')
            digest = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
            request = self.run / ('approval-' + digest[:16] + '.json')
            answer = self.run / ('decision-' + digest[:16] + '.json')
            write_json(request, {'digest': digest, 'threadId': self.thread,
                                 'request': event, 'decisionFile': str(answer)})
            print(json.dumps({'event': 'approval_pending', 'file': str(request)}), flush=True)
            end = time.monotonic() + 3600
            while time.monotonic() < end:
                if answer.exists():
                    data = json.loads(answer.read_text(encoding='utf-8'))
                    if (data.get('digest') != digest or data.get('threadId') != self.thread
                            or data.get('source') != 'explicit-user-answer'
                            or data.get('decision') not in ('accept', 'decline', 'cancel')):
                        raise RuntimeError('审批决定身份或类型不匹配，不自动放行')
                    self.ws.send(json.dumps({'id': event['id'], 'result': {
                        'decision': data['decision']}}))
                    return {'method': 'mentor/decisionRelayed', 'params': {'threadId': self.thread}}
                threading.Event().wait(0.5)
            self.ws.send(json.dumps({'id': event['id'], 'result': {'decision': 'cancel'}}))
            raise TimeoutError('未收到用户决定，取消本请求，未授予权限')
        return event

    def call(self, method, params):
        self.sequence += 1
        key = self.sequence
        self.ws.send(json.dumps({'id': key, 'method': method, 'params': params}))
        end = time.monotonic() + 60
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('RPC超时：' + method)
            event = self.receive(remaining)
            if event.get('id') == key and 'method' not in event:
                if 'error' in event:
                    raise RuntimeError(method + ': ' + str(event['error']))
                return event.get('result')
            self.events.append(event)

    def read_thread(self):
        data = self.call('thread/read', {'threadId': self.thread, 'includeTurns': True})['thread']
        if data['id'] != self.thread:
            raise RuntimeError('返回会话与目标不符')
        return data

    def wait(self, turn_id, seconds):
        end = time.monotonic() + seconds
        with (self.run / 'events.jsonl').open('a', encoding='utf-8') as log:
            while time.monotonic() < end:
                event = self.events.popleft() if self.events else self.receive(end - time.monotonic())
                params = event.get('params', {})
                if params.get('threadId') != self.thread:
                    continue
                # 不复制命令输出/思考流到另一份日志；详细过程在桌面查看。
                summary = {'method': event.get('method'), 'threadId': self.thread,
                           'turnId': params.get('turnId')}
                log.write(json.dumps(summary) + '\n')
                log.flush()
                if (event.get('method') == 'turn/completed'
                        and params.get('turn', {}).get('id') == turn_id):
                    return params['turn']
        raise TimeoutError('等待结束；必须recover原回合，不重复发送任务')


def check_resume(thread, manifest, project):
    if str(Path(thread['cwd']).resolve()).casefold() != str(project).casefold():
        raise RuntimeError('会话项目目录不符')
    turns = thread.get('turns', [])
    if any(t.get('status') not in TERMINAL for t in turns):
        raise RuntimeError('存在运行中或未知回合，先recover，不重复派单')
    if manifest.get('phase') in ('starting', 'unknown', 'running'):
        raise RuntimeError('上次调用结果未核实，先recover')


def result_for(turn):
    return {'status': turn.get('status', 'unknown'), 'error': turn.get('error'),
            'finalMessage': final_message(turn)}


def send(args):
    task = Path(args.task).resolve()
    project = Path(args.project).resolve()
    prompt = Path(args.prompt).read_text(encoding='utf-8')
    if not project.is_dir() or not prompt.strip():
        raise ValueError('项目目录不存在或任务消息为空')
    evidence = desktop_evidence(args.url)
    task.mkdir(parents=True, exist_ok=True)
    manifest_path = task / 'task.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    if manifest and (manifest['project'] != str(project) or manifest['mode'] != args.mode
                     or manifest['url'] != args.url):
        raise RuntimeError('项目/权限/连接与已记录任务不符，不隐式切换')
    # 每任务单一派单锁；崩溃遗留锁需检查原进程与回合后人工解除。
    lock = task / 'dispatch.lock'
    with lock.open('x', encoding='utf-8') as f:
        f.write(str(__import__('os').getpid()))
    rpc = None
    run = task / ('turn-' + uuid.uuid4().hex)
    try:
        run.mkdir()
        (run / 'request.md').write_text(prompt, encoding='utf-8')
        rpc = Rpc(args.url, run=run, thread=manifest.get('threadId'))
        if manifest:
            check_resume(rpc.read_thread(), manifest, project)
            rpc.call('thread/resume', {'threadId': rpc.thread})
        else:
            data = rpc.call('thread/start', {'cwd': str(project), 'sandbox': args.mode,
                                            'approvalPolicy': 'on-request'})
            rpc.thread = data['thread']['id']
            manifest = {'project': str(project), 'mode': args.mode, 'url': args.url,
                        'threadId': rpc.thread}
            # 同一连接创建和启动；无rollout的新会话不能跨连接resume。
        manifest.pop('turnId', None)
        manifest.update({'phase': 'starting', 'run': str(run), 'desktopEvidence': evidence})
        write_json(manifest_path, manifest)
        data = rpc.call('turn/start', {'threadId': rpc.thread, 'input': [
            {'type': 'text', 'text': prompt, 'text_elements': []}]})
        manifest.update({'phase': 'running', 'turnId': data['turn']['id']})
        write_json(manifest_path, manifest)
        write_json(run / 'state.json', manifest)
        print(json.dumps({'event': 'turn_started', 'run': str(run),
                          'threadId': rpc.thread, 'turnId': manifest['turnId']}), flush=True)
        turn = rpc.wait(manifest['turnId'], args.wait)
        result = result_for(turn)
        write_json(run / 'result.json', result)
        manifest['phase'] = result['status'] if result['status'] in TERMINAL else 'unknown'
        write_json(manifest_path, manifest)
        if result['status'] != 'completed' or result['error']:
            raise RuntimeError('目标回合未正常完成，检查result.json')
    except Exception as error:
        write_json(run / 'dispatch-error.json', {'status': 'unknown', 'error': str(error)})
        if manifest.get('phase') in ('starting', 'running'):
            manifest['phase'] = 'unknown'
            write_json(manifest_path, manifest)
        raise
    finally:
        try:
            if rpc:
                rpc.close()
        finally:
            lock.unlink(missing_ok=True)


def recover(args):
    path = Path(args.task).resolve() / 'task.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    rpc = Rpc(manifest['url'], thread=manifest['threadId'])
    try:
        thread = rpc.read_thread()
        turns = thread.get('turns', [])
        turn_id = manifest.get('turnId')
        # turn/start应答丢失时仅展示候选历史，不能猜测最新回合就是本次。
        turn = next((t for t in turns if t['id'] == turn_id), None) if manifest['phase'] != 'starting' else None
        result = result_for(turn) if turn else {'status': 'unknown', 'turnIds': [t['id'] for t in turns]}
        write_json(Path(manifest['run']) / 'recovery.json', result)
        if turn and result['status'] in TERMINAL:
            manifest['phase'] = result['status']
            write_json(path, manifest)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        rpc.close()


def watch(args):
    run = Path(args.run)
    seen = set()
    end = time.monotonic() + args.seconds
    while time.monotonic() < end:
        for path in run.glob('approval-*.json'):
            if path.name not in seen:
                data = json.loads(path.read_text(encoding='utf-8'))
                if not Path(data['decisionFile']).exists():
                    print(json.dumps({'event': 'approval_pending', 'file': str(path)}), flush=True)
                seen.add(path.name)
        for name in ('result.json', 'recovery.json', 'dispatch-error.json'):
            path = run / name
            if path.exists():
                print(json.dumps({'event': name, 'file': str(path)}), flush=True)
                return
        threading.Event().wait(1)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    d = sub.add_parser('doctor')
    d.add_argument('--url', default='ws://127.0.0.1:18765')
    server = sub.add_parser('serve')
    server.add_argument('--codex', required=True)
    server.add_argument('--url', default='ws://127.0.0.1:18765')
    s = sub.add_parser('send')
    s.add_argument('--url', default='ws://127.0.0.1:18765')
    for name in ('task', 'project', 'prompt'):
        s.add_argument('--' + name, required=True)
    s.add_argument('--mode', choices=('read-only', 'workspace-write'), required=True)
    s.add_argument('--wait', type=int, default=36000)
    r = sub.add_parser('recover')
    r.add_argument('--task', required=True)
    w = sub.add_parser('watch')
    w.add_argument('--run', required=True)
    w.add_argument('--seconds', type=int, default=1750)
    args = p.parse_args()
    if args.command == 'serve':
        exe = Path(args.codex).resolve()
        if not exe.is_file():
            raise ValueError('Codex可执行文件不存在')
        subprocess.run([str(exe), '-c', 'analytics.enabled=false', '-c',
                        'features.code_mode_host=true', 'app-server', '--listen',
                        local_url(args.url)], check=True)
    elif args.command == 'doctor':
        evidence = desktop_evidence(args.url)
        rpc = Rpc(args.url)
        rpc.close()
        print(json.dumps({'status': 'connected', **evidence}))
    elif args.command == 'send':
        send(args)
    elif args.command == 'recover':
        recover(args)
    else:
        watch(args)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
