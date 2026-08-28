#!/usr/bin/env python3
"""
Fetch CM6 non-bundled ESM from esm.sh and rewrite all esm.sh absolute imports
to bare specifiers, so they can be unified via an import map.

This solves the 'multiple instances of @codemirror/state' problem: every module
imports @codemirror/state from the same mapped URL.
"""
import os, urllib.request, re

VENDOR = os.path.dirname(os.path.abspath(__file__))
BASE = "https://esm.sh"

# (esm.sh spec, local filename, list of bare deps it imports)
MODULES = [
    ("@codemirror/state@6.4.1", "state.mjs"),
    ("@codemirror/view@6.34.1", "view.mjs"),
    ("@codemirror/commands@6.7.1", "commands.mjs"),
    ("@codemirror/language@6.10.3", "language.mjs"),
    ("@codemirror/autocomplete@6.18.1", "autocomplete.mjs"),
    ("@codemirror/search@6.5.6", "search.mjs"),
    ("@codemirror/lang-markdown@6.3.0", "lang-markdown.mjs"),
    ("@codemirror/lang-python@6.1.6", "lang-python.mjs"),
    ("@codemirror/lang-cpp@6.0.2", "lang-cpp.mjs"),
    ("@codemirror/lang-rust@6.0.1", "lang-rust.mjs"),
    ("@codemirror/lang-javascript@6.2.2", "lang-javascript.mjs"),
    ("@codemirror/lang-json@6.0.1", "lang-json.mjs"),
    ("@codemirror/lang-html@6.4.9", "lang-html.mjs"),
    ("@codemirror/lang-css@6.3.0", "lang-css.mjs"),
    ("@codemirror/lang-yaml@6.1.1", "lang-yaml.mjs"),
    ("@codemirror/theme-one-dark@6.1.2", "theme-one-dark.mjs"),
    ("@lezer/common@1.2.1", "lezer-common.mjs"),
    ("@lezer/highlight@1.2.1", "lezer-highlight.mjs"),
    ("@lezer/lr@1.4.2", "lezer-lr.mjs"),
    ("@lezer/markdown@1.4.0", "lezer-markdown.mjs"),
    ("@lezer/python@1.1.13", "lezer-python.mjs"),
    ("@lezer/cpp@1.1.1", "lezer-cpp.mjs"),
    ("@lezer/rust@1.0.2", "lezer-rust.mjs"),
    ("@lezer/javascript@1.4.17", "lezer-javascript.mjs"),
    ("@lezer/json@1.0.2", "lezer-json.mjs"),
    ("@lezer/html@1.3.10", "lezer-html.mjs"),
    ("@lezer/css@1.1.8", "lezer-css.mjs"),
    ("@lezer/yaml@1.0.3", "lezer-yaml.mjs"),
    ("crelt@1.0.6", "crelt.mjs"),
    ("style-mod@4.1.2", "style-mod.mjs"),
    ("w3c-keyname@2.2.8", "w3c-keyname.mjs"),
]


def _bare_from_path(path):
    """Convert esm.sh path '/@lezer/lr@^1.0.0?target=es2022' → '@lezer/lr'."""
    bare = path.lstrip("/")
    # Remove query string
    bare = bare.split("?")[0]
    if bare.startswith("@"):
        # @scope/pkg@ver → @scope/pkg
        parts = bare.split("/")
        scope = parts[0]
        rest = "/".join(parts[1:])
        if "@" in rest:
            rest = rest.split("@")[0]
        bare = scope + "/" + rest
    else:
        # pkg@ver → pkg (only strip version, not the whole string)
        # careful: 'w3c-keyname@^2.2.4' → 'w3c-keyname'
        bare = re.sub(r"@[^/]*$", "", bare)
    return bare


def fetch_nonbundle(spec):
    """Fetch non-bundled ESM from esm.sh, return rewritten content."""
    name = spec.split("/")[-1].split("@")[0]
    url = f"{BASE}/{spec}/es2022/{name}.mjs"
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    with urllib.request.urlopen(req, timeout=60) as r:
        content = r.read().decode("utf-8")

    # Rewrite esm.sh absolute imports to bare specifiers
    content = re.sub(r'from"(/[^"]+)"', lambda m: f'from"{_bare_from_path(m.group(1))}"', content)
    # Also rewrite dynamic imports
    content = re.sub(r'import\("(/[^"]+)"\)', lambda m: f'import("{_bare_from_path(m.group(1))}")', content)
    return content


def main():
    failures = []
    for spec, outfile in MODULES:
        path = os.path.join(VENDOR, outfile)
        try:
            content = fetch_nonbundle(spec)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            # Count imports
            imports = re.findall(r'from"([^"]+)"', content)
            print(f"  [ok] {outfile:24} ({len(content):>7} chars, {len(imports)} imports)")
        except Exception as e:
            print(f"  [FAIL] {outfile}: {e}")
            failures.append(outfile)
    print(f"\ndone. failures: {failures or 'none'}")


if __name__ == "__main__":
    main()
