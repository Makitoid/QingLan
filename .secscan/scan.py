#!/usr/bin/env python3
"""Resolve installed versions, query OSV.dev, emit compact findings."""
import json, subprocess, sys, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

ROOT = r"D:/somehow/GitHub/qinglan"
OSV = "https://api.osv.dev/v1/query"


def pip_pkgs():
    out = subprocess.run(
        [ROOT + "/backend/.venv/Scripts/python.exe", "-m", "pip", "freeze"],
        capture_output=True, text=True).stdout
    res = {}
    for line in out.splitlines():
        if "==" in line:
            n, v = line.split("==", 1)
            res[n.split("[")[0].lower()] = v
    return res


def npm_pkgs():
    lock = json.load(open(ROOT + "/frontend/package-lock.json", encoding="utf-8"))
    prod = set()
    pkg = lock.get("packages", {}).get("", {})
    prod |= set(pkg.get("dependencies", {}))
    prod |= {k for k, v in lock.get("dependencies", {}).items()
             if not v.get("dev")}
    res = {}
    for name, meta in lock.get("packages", {}).items():
        if not name.startswith("node_modules/") or meta.get("dev"):
            continue
        base = name.rsplit("node_modules/", 1)[-1]
        if base in prod or base.startswith("@fluentui/") or base.startswith("@codemirror/"):
            res[base] = meta.get("version", "")
    return res


SEV_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}


def severity(v):
    best = 0.0
    for s in v.get("severity", []):
        try:
            best = max(best, float(s.get("score", "")))
        except ValueError:
            pass
    if not best:
        for sv in v.get("database_specific", {}).get("severity", "") or "":
            pass
        ds = (v.get("database_specific") or {}).get("severity")
        if isinstance(ds, str):
            best = {"CRITICAL": 9.5, "HIGH": 7.5, "MODERATE": 5.5, "LOW": 2.5}.get(ds.upper(), 0)
    lvl = ("CRITICAL" if best >= 9 else "HIGH" if best >= 7 else
           "MEDIUM" if best >= 4 else "LOW" if best > 0 else "UNKNOWN")
    return round(best, 1), lvl


def query(arg):
    name, ver, eco = arg
    payload = {"package": {"name": name, "ecosystem": eco}}
    if ver:
        payload["version"] = ver
    req = urllib.request.Request(
        OSV, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            vulns = json.loads(r.read().decode()).get("vulns", [])
    except Exception as e:
        return {"package": name, "version": ver, "error": str(e)[:120], "findings": []}
    out = []
    for v in vulns:
        score, lvl = severity(v)
        fixed = []
        for a in v.get("affected", []):
            for r_ in a.get("ranges", []):
                for ev in r_.get("events", []):
                    if "fixed" in ev:
                        fixed.append(ev["fixed"])
        out.append({
            "id": v.get("id"),
            "cves": [a for a in v.get("aliases", []) if a.startswith("CVE-")],
            "sev": lvl, "cvss": score,
            "summary": (v.get("summary") or "")[:200],
            "fixed_in": sorted(set(fixed))[-3:],
            "kev": bool((v.get("database_specific") or {}).get("cisa_kev")) or
                   any("kev" in str(r).lower() for r in (v.get("references") or [])),
            "published": (v.get("published") or "")[:10],
        })
    return {"package": name, "version": ver, "ecosystem": eco, "findings": out}


def main():
    pkgs = [("pip", n, v) for n, v in pip_pkgs().items()]
    pkgs += [("npm", n, v) for n, v in npm_pkgs().items()]
    args = [(n, v, "PyPI" if e == "pip" else "npm") for e, n, v in pkgs]
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(query, args))
    hits = [r for r in results if r["findings"] or r.get("error")]
    total = {"pip": len(pip_pkgs()), "npm": len(npm_pkgs())}
    json.dump({"scanned": total, "results": hits, "errors": [
        r for r in hits if r.get("error")]}, open(
        ROOT + "/.secscan/osv.json", "w", encoding="utf-8"), indent=1)
    print(f"scanned pip={total['pip']} npm={total['npm']} -> hits={len(hits)}")
    for r in hits:
        if r.get("error"):
            print("ERR", r["package"], r["error"])
        for f in r["findings"]:
            print(f"{f['sev']:8} {f['cvss']:5} {r['package']:32}{r['version']:12}"
                  f" {f['id']:16} {','.join(f['cves'])[:24]:26} fix={','.join(f['fixed_in']):14} {f['summary'][:60]}")


main()
