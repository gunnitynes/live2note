#!/usr/bin/env python3
"""Round trip against Live's own exporter.

For every .ablpresetbundle Live exported, find the rack it came from in the .als files
next to it, convert that rack with live2note, and diff the two JSON documents.
A rack the user edited after exporting will differ in VALUES; what must never differ
is STRUCTURE (keys, kinds, nesting, types). Usage:  roundtrip.py FOLDER [FOLDER...]
"""
import glob, json, math, sys, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import live2note as L


def flat(x, p=""):
    if isinstance(x, dict):
        for k, v in x.items():
            if k in ("$schema", "presetUri") or (k == "name" and p == ""):
                continue
            yield from flat(v, f"{p}/{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from flat(v, f"{p}[{i}]")
    else:
        yield p, x


def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-5, abs_tol=1e-6)
        except (TypeError, ValueError):
            return False
    return a == b


def main(folders):
    candidates = []                     # (src file, name, converted preset)
    for folder in folders:
        for f in glob.glob(f"{folder}/**/*.als", recursive=True):
            r = L.Report(f)
            try:
                for name, obj in L.racks_in(f, r):
                    c = L.Converter(f, L.Report(name))
                    c.sample = lambda cell, c=c: _sample_name(cell)
                    p = c.preset(name, obj)
                    if p:
                        candidates.append((f, name, dict(flat(p))))
            except Exception as e:
                print("skip", f, e)
        # racks nested anywhere (e.g. a preset rack inside a chain) are candidates too
    print(f"{len(candidates)} source racks found")

    struct_bad = exact = close = 0
    bundles = [b for folder in folders
               for b in glob.glob(f"{folder}/**/*.ablpresetbundle", recursive=True)]
    for b in sorted(bundles):
        live = dict(flat(json.loads(zipfile.ZipFile(b).read("Preset.ablpreset"))))
        best = None
        for f, name, mine in candidates:
            keys_eq = set(mine) == set(live)
            agree = sum(same(mine.get(k), v) for k, v in live.items())
            score = (keys_eq, agree)
            if best is None or score > best[0]:
                best = (score, f, name, mine)
        (keys_eq, agree), f, name, mine = best
        frac = agree / len(live)
        missing = sorted(set(live) - set(mine))
        extra = sorted(set(mine) - set(live))
        type_bad = [k for k in set(live) & set(mine)
                    if type(live[k]) is not type(mine[k])
                    and not ({type(live[k]), type(mine[k])} <= {int, float} and False)]
        tag = "EXACT" if frac == 1 and keys_eq else ("same structure" if keys_eq and not type_bad else "STRUCTURE DIFFERS")
        exact += tag == "EXACT"; struct_bad += tag == "STRUCTURE DIFFERS"
        print(f"{Path(b).name:32s} {tag:18s} {agree}/{len(live)} values agree  "
              f"<- {Path(f).name} :: {name}")
        if tag == "STRUCTURE DIFFERS":
            for k in missing[:6]: print("     missing", k, live[k])
            for k in extra[:6]: print("     extra  ", k, mine[k])
            for k in type_bad[:6]: print("     type   ", k, repr(live[k]), repr(mine[k]))
        elif frac > 0.97 and frac < 1:
            for k, v in live.items():
                if not same(mine.get(k), v):
                    print(f"     {k}: live={v!r} mine={mine.get(k)!r}")
    print(f"\n{len(bundles)} bundles: {exact} exact, {struct_bad} structural mismatches")
    return 1 if struct_bad else 0


def _sample_name(cell):
    fr = cell.find("UserSample/Value/SampleRef/FileRef")
    if fr is None:
        return None
    return "Samples/" + Path(L.val(fr, "Path", "") or L.val(fr, "RelativePath", "")).name


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["/Volumes/T7/VINNUSTOFA/NOTE"]))
