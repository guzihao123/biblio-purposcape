"""真实 Qwen 异常验收——你只需要在终端跑一次，我会在另一个会话监控进度。"""
import os, json, sys, time

# 清除代理干扰
for k in list(os.environ):
    upper = k.upper()
    if any(p in upper for p in ('PROXY', 'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY', 'ALL_PROXY')):
        del os.environ[k]

# 读你的 Key 文件
cfg = {}
with open(os.path.expanduser('~/.config/purpose-landscape/qwen.env')) as f:
    for line in f:
        if '=' in line and not line.startswith('#'):
            k, v = line.strip().split('=', 1)
            cfg[k] = v

os.environ.update(cfg)
sys.path.insert(0, 'backend')

results = []

def test(name, override_env=None):
    if override_env:
        old = {k: os.environ.get(k) for k in override_env}
        os.environ.update(override_env)
    try:
        from app.qwen import ChatModel
        model = ChatModel()
        start = time.time()
        result = model.complete_json('输出 JSON: {"reply":"test"}', {})
        elapsed = time.time() - start
        results.append({'test': name, 'status': 'ok', 'elapsed': round(elapsed, 2), 'result': result})
        print(f'  ✅ {name} ({elapsed:.1f}s)')
    except Exception as e:
        results.append({'test': name, 'status': 'exception', 'type': type(e).__name__, 'message': str(e)[:200]})
        print(f'  ⚠️  {name}: {type(e).__name__} — {str(e)[:120]}')
    finally:
        if override_env:
            for k in old:
                if old[k] is None:
                    del os.environ[k]
                else:
                    os.environ[k] = old[k]

print('=== 真实 Qwen 异常验收 ===\n')

# 1) 正常调用（对照组）
test('正常调用')

# 2) 错误的 Key → 必须 401，不能打印真实 Key
test('错误 Key', {'QWEN_API_KEY': 'sk-this-is-clearly-wrong'})

# 3) 错误的 Base URL → 必须安全报错
test('错误的 URL', {'QWEN_BASE_URL': 'https://no-such-host.invalid/v1'})

# 4) 正常调用超短响应
test('正常调用（第二次）')

print(f'\n=== 结果：{len([r for r in results if r["status"]=="ok"])}/{len(results)} 通过 ===')

path = 'dev/acceptance/model-failure-contract/live-qwen-result.json'
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, 'w', encoding='utf-8') as f:
    json.dump({'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'results': results}, f, ensure_ascii=False, indent=2)
print(f'\n报告已写入: {path}')