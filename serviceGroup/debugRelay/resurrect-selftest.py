"""resurrect 自测: 检查 window.resurrect 存在 → reload 如需 → runAll + openView + probeDrawcall"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:5003"

def api_eval(expr: str, timeout: float = 10.0):
    body = json.dumps({"expr": expr, "timeout": timeout}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/eval", data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout + 5) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}

def api_reload():
    req = urllib.request.Request(f"{BASE}/api/runtime/reload", data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}

def run():
    print("=== 1. 检查 window.resurrect 是否存在 ===")
    r = api_eval("typeof window.resurrect")
    print(f"  {r}")
    exists = r.get("eval_result") == "object"

    if not exists:
        print("=== window.resurrect 未挂载, 尝试 runtime_reload ===")
        rr = api_reload()
        print(f"  {rr}")
        time.sleep(6)
        r = api_eval("typeof window.resurrect")
        print(f"  reload 后: {r}")
        exists = r.get("eval_result") == "object"

    if not exists:
        print("=== FAIL: window.resurrect 仍不存在 (可能编辑器未编译 TS 或 Plugin 未 onInit) ===")
        # 再查 ResurrectPlugin 是否加载
        r2 = api_eval("typeof ResurrectPlugin")
        print(f"  typeof ResurrectPlugin: {r2}")
        sys.exit(1)

    print("\n=== 2. window.resurrect 接口清单 ===")
    r = api_eval("Object.keys(window.resurrect).join(',')")
    print(f"  keys: {r.get('eval_result')}")

    print("\n=== 3. runUnitTest() ===")
    r = api_eval(
        "(() => { try { const r = window.resurrect.runUnitTest(); "
        "return 'passed=' + r.passed + ' failed=' + r.failed + ' total=' + r.total; } "
        "catch(e) { return 'EXCEPTION: ' + e.message + ' :: ' + (e.stack||'').split('\\n').slice(0,3).join(' | '); } })()",
        timeout=20,
    )
    print(f"  {r.get('eval_result')}")

    print("\n=== 4. runIntegrationTest() ===")
    r = api_eval(
        "(() => { try { const r = window.resurrect.runIntegrationTest(); "
        "return 'passed=' + r.passed + ' failed=' + r.failed + ' total=' + r.total; } "
        "catch(e) { return 'EXCEPTION: ' + e.message; } })()",
        timeout=20,
    )
    print(f"  {r.get('eval_result')}")

    print("\n=== 5. 完整 runAll output (含失败详情) ===")
    r = api_eval(
        "(() => { try { const r = window.resurrect.runAll(); return r.output; } "
        "catch(e) { return 'EXCEPTION: ' + e.message; } })()",
        timeout=30,
    )
    out = r.get("eval_result", "")
    print(out if out else f"  {r}")

    print("\n=== 6. probeDrawcall() (drawcall 探针) ===")
    r = api_eval(
        "(() => { try { const r = window.resurrect.probeDrawcall({closeAfter: true}); "
        "return 'scenario=' + r.scenario + ' drawcall=' + r.drawcall; } "
        "catch(e) { return 'EXCEPTION: ' + e.message; } })()",
        timeout=15,
    )
    print(f"  {r.get('eval_result')}")

if __name__ == "__main__":
    run()
