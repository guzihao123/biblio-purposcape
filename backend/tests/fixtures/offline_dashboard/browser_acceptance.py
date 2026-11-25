#!/usr/bin/env python3
"""Real Chromium acceptance: local HTTP, strict CSP, blocked external network, no-JS."""
import argparse
import json
import platform
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit

from playwright.sync_api import sync_playwright


TITLES = ('总体趋势', '主题分布', '比较分析', '引用', '因素', '研究方法', '语义关系')
INTERACTIVE_IDS = ('trend', 'topics', 'compare', 'network', 'knowledge', 'methods', 'relations')
CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'none'; connect-src 'none'; object-src 'none'; "
    "base-uri 'none'; form-action 'none'"
)
CSP_NOJS = CSP.replace("script-src 'unsafe-inline'", "script-src 'none'")


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        if urlsplit(self.path).path.endswith('.html'):
            csp = CSP_NOJS if urlsplit(self.path).query == 'nojs' else CSP
            self.send_header('Content-Security-Policy', csp)
            self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, fmt, *args):
        return


def browser_executable():
    root = Path.home() / 'Library' / 'Caches' / 'ms-playwright'
    candidates = sorted(root.glob('chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'))
    if candidates:
        return str(candidates[-1])
    return None


def visible(page, selector):
    return page.locator(selector).is_visible()


def run_scenario(browser, base_url, output, name, path, js=True, empty=False, image=False):
    context = browser.new_context(
        java_script_enabled=js,
        viewport={'width': 1440, 'height': 1000},
        device_scale_factor=1,
    )
    events = {'console': [], 'pageerror': [], 'requestfailed': [], 'requests': [], 'responses': [], 'external_blocked': []}
    local_prefix = base_url + '/'

    def guard(route):
        url = route.request.url
        if url.startswith(local_prefix):
            route.continue_()
        else:
            events['external_blocked'].append({'url': url, 'resource_type': route.request.resource_type})
            route.abort('internetdisconnected')

    context.route('**/*', guard)
    page = context.new_page()
    page.on('console', lambda msg: events['console'].append({'type': msg.type, 'text': msg.text}))
    page.on('pageerror', lambda exc: events['pageerror'].append(str(getattr(exc, 'stack', exc))))
    page.on('request', lambda request: events['requests'].append({'method': request.method, 'url': request.url, 'resource_type': request.resource_type}))
    page.on('requestfailed', lambda request: events['requestfailed'].append({'url': request.url, 'failure': request.failure}))
    page.on('response', lambda response: events['responses'].append({'url': response.url, 'status': response.status, 'csp': response.headers.get('content-security-policy', '')}))
    result = {'scenario': name, 'url': base_url + '/' + quote(path) + ('?nojs' if not js and not image else ''), 'javascript': js, 'checks': {}, 'events_file': name + '.json'}
    try:
        page.goto(result['url'], wait_until='load', timeout=60000)
        page.wait_for_timeout(1800 if js else 300)
        if image:
            result['checks']['visible_image'] = page.locator('img, svg').count() > 0
        else:
            body = page.locator('body').inner_text()
            for title in TITLES:
                result['checks']['title:' + title] = title in body
        if not image and js and not empty:
            if path.endswith('mobile.html'):
                for selector in ('#trend-live svg', '#compare-live svg', '#topics-live-all svg', 'img.longshot'):
                    result['checks']['rendered:' + selector] = page.locator(selector).count() > 0
                result['checks']['long_image_loaded'] = page.locator('img.longshot').evaluate('(img) => img.complete && img.naturalWidth > 0')
                page.locator('[data-panel="all-kg-e0"]').first.dispatch_event('click')
                result['checks']['factor_evidence_panel'] = visible(page, '#all-kg-e0') and '摘要原句' in page.locator('#all-kg-e0').inner_text()
                page.locator('[data-panel="all-rel-e0"]').first.dispatch_event('click')
                result['checks']['semantic_evidence_panel'] = visible(page, '#all-rel-e0') and '双方摘要原句' in page.locator('#all-rel-e0').inner_text()
            else:
                for chart_id in INTERACTIVE_IDS:
                    result['checks']['rendered:' + chart_id] = page.locator('#' + chart_id + ' svg,#' + chart_id + ' canvas').count() > 0
                if path.startswith('real/文献'):
                    result['checks']['static_fallback_hidden'] = not visible(page, '#staticFallback')
                    page.locator('#tabs button[data-scope="limited"]').click()
                    result['checks']['dual_scope_switch'] = '限定' in page.locator('#topicsScope').inner_text()
                    page.locator('#tabs button[data-scope="all"]').click()
        elif not image and js and empty:
            if path.endswith('mobile.html'):
                result['checks']['explicit_empty_svgs'] = page.locator('main svg').count() >= 7
            else:
                result['checks']['explicit_empty_states'] = page.locator('.empty').count() >= 7
        elif not image and not js:
            if path.endswith('mobile.html'):
                result['checks']['static_svgs_present'] = page.locator('main svg').count() >= 7
                result['checks']['static_svg_visible'] = page.locator('main svg:visible').count() > 0
            else:
                result['checks']['fallback_visible'] = visible(page, '#staticFallback')
                result['checks']['fallback_svgs'] = page.locator('#staticFallback svg').count() >= 7
                result['checks']['interactive_sections_hidden'] = page.locator('.chartsec:visible').count() == 0
        result['checks']['no_pageerror'] = not events['pageerror']
        result['checks']['no_external_request'] = not events['external_blocked']
        result['checks']['no_requestfailed'] = not events['requestfailed']
        if js:
            result['checks']['no_console_error'] = not any(item['type'] == 'error' for item in events['console'])
        result['checks']['strict_csp_header'] = image or any(item.get('csp') for item in events['responses'] if item['url'].endswith('.html') or '.html?' in item['url'])
        screenshot = output / (name + '.png')
        page.screenshot(path=str(screenshot), full_page=not image)
        result['screenshot'] = screenshot.name
    except Exception as exc:
        result['exception'] = repr(exc)
        result['checks']['navigation_completed'] = False
    result['passed'] = bool(result['checks']) and all(result['checks'].values())
    (output / (name + '.json')).write_text(json.dumps({'result': result, **events}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    context.close()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    artifacts = Path(args.artifacts).resolve()
    output = Path(args.out).resolve()
    output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(artifacts)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = 'http://127.0.0.1:%d' % server.server_port
    scenarios = [
        ('real-dashboard-offline-csp', 'real/文献图谱仪表盘.html', True, False, False),
        ('real-desktop-offline-csp', 'real/desktop.html', True, False, False),
        ('real-mobile-offline-csp', 'real/mobile.html', True, False, False),
        ('real-dashboard-nojs-csp', 'real/文献图谱仪表盘.html', False, False, False),
        ('real-mobile-nojs-csp', 'real/mobile.html', False, False, False),
        ('empty-dashboard-offline-csp', 'empty/文献图谱仪表盘.html', True, True, False),
        ('empty-desktop-offline-csp', 'empty/desktop.html', True, True, False),
        ('empty-mobile-nojs-csp', 'empty/mobile.html', False, True, False),
        ('real-long-svg', 'real/文献图谱仪表盘.svg', False, False, True),
        ('real-long-png', 'real/文献图谱仪表盘.png', False, False, True),
    ]
    results = []
    try:
        with sync_playwright() as p:
            executable = browser_executable()
            browser = p.chromium.launch(headless=True, executable_path=executable) if executable else p.chromium.launch(headless=True)
            for scenario in scenarios:
                result = run_scenario(browser, base_url, output, *scenario)
                results.append(result)
                print(scenario[0], 'PASS' if result['passed'] else 'FAIL')
            environment = {
                'browser': 'Chromium ' + browser.version,
                'executable': executable or p.chromium.executable_path,
                'platform': platform.platform(),
                'base_url': base_url,
                'external_policy': 'Abort every non-127.0.0.1 request with internetdisconnected',
                'csp': CSP,
                'nojs_csp': CSP_NOJS,
            }
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    summary = {'environment': environment, 'scenarios': results, 'passed': all(item['passed'] for item in results)}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (output / 'commands.txt').write_text(
        '.venv/bin/python backend/tests/fixtures/offline_dashboard/browser_acceptance.py '
        '--artifacts deliverables/offline-dashboard --out deliverables/offline-dashboard/browser-evidence\n',
        encoding='utf-8',
    )
    raise SystemExit(0 if summary['passed'] else 1)


if __name__ == '__main__':
    main()
