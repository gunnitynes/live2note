#!/usr/bin/env python3
"""live2note — turn Live instruments into Ableton Note presets, no hidden flag needed.

    live2note.py convert  MyRack.adg [more.adg ...]  [-o OUTDIR]
    live2note.py convert  MySet.als                  (every track whose instrument Note can play)
    live2note.py check    MyRack.adg                 (what would fail on the phone, and why)
    live2note.py watch    [INBOX] [-o OUTDIR]        (save a rack into INBOX -> bundle appears)

An .ablpresetbundle is a zip: Preset.ablpreset (JSON), BundleInfo.json, Samples/*.
Live's .adg/.als are gzipped XML whose parameter names ARE Note's names; the work is
the structure around them, the enum labels (devices.py) and the samples.
"""
import argparse, gzip, json, math, os, re, sys, time, urllib.parse, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import devices as D

SCHEMA = json.loads((Path(__file__).resolve().parent / "note_schema.json").read_text())
SCHEMA_URL = "http://tech.ableton.com/schema/song/1.7.0/devicePreset.json"
USER_LIBRARY = Path.home() / "Music/Ableton/User Library"


class Report:
    def __init__(self, name):
        self.name, self.errors, self.warnings, self.notes = name, [], [], []

    def error(self, m): self.errors.append(m)
    def warn(self, m): self.warnings.append(m)
    def note(self, m): self.notes.append(m)

    def print(self):
        mark = "FAIL" if self.errors else "ok  "
        print(f"[{mark}] {self.name}")
        for m in self.errors: print(f"       x {m}")
        for m in self.warnings: print(f"       ! {m}")
        for m in self.notes: print(f"       . {m}")


# ---------------------------------------------------------------- XML helpers

def read_xml(path):
    raw = Path(path).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return ET.fromstring(raw)


def val(e, name, default=None):
    """Value of a parameter: <X><Manual Value=..>  or  <X Value=..>."""
    c = e.find(name)
    if c is None:
        return default
    m = c.find("Manual")
    return (m if m is not None else c).get("Value", default)


def num(s):
    f = float(s)
    return int(f) if f.is_integer() else f


def to_db(lin):
    lin = float(lin)
    return -math.inf if lin <= 0 else 20 * math.log10(lin)


# ---------------------------------------------------------------- two layouts
# A rack in an .als holds its chains (Branches/*Branch) inside the device element.
# A rack in an .adg is a GroupDevicePreset: Device/<Rack> + BranchPresets/*BranchPreset.
# Both are normalised to: Rack(device_elem, chains=[Chain], returns=[Chain]).

class Chain:
    def __init__(self, name, color, devices, mixer, zone=None):
        self.name, self.color, self.devices, self.mixer, self.zone = name, color, devices, mixer, zone


class Rack:
    def __init__(self, elem, chains, returns):
        self.elem, self.chains, self.returns = elem, chains, returns
        self.tag = elem.tag


def _kids(e):
    return list(e) if e is not None else []


def _devices_in_chain_elem(chain_elem):
    out = []
    dc = chain_elem.find("DeviceChain")
    devs = dc.find(".//Devices") if dc is not None else None
    for d in (devs if devs is not None else []):
        out.append(_wrap_live_device(d))
    return out


def _wrap_live_device(d):
    if d.tag in ("InstrumentGroupDevice", "DrumGroupDevice", "AudioEffectGroupDevice"):
        chains = [Chain(val(b, "Name/EffectiveName", "") or "", int(val(b, "Color", 0) or 0),
                        _devices_in_chain_elem(b), b.find("MixerDevice"),
                        b.find("BranchInfo"))
                  for b in _kids(d.find("Branches"))]
        returns = [Chain("", int(val(b, "Color", 0) or 0), _devices_in_chain_elem(b),
                         b.find("MixerDevice"))
                   for b in _kids(d.find("ReturnBranches"))]
        return Rack(d, chains, returns)
    return d


def _wrap_preset(p):
    """p is AbletonDevicePreset or GroupDevicePreset (from an .adg)."""
    dev = p.find("Device")
    dev = dev[0] if dev is not None and len(dev) else None
    if p.tag != "GroupDevicePreset":
        return dev
    def chains_of(container_tag):
        out = []
        for b in _kids(p.find(container_tag)):
            mix = b.find("MixerPreset/AbletonDevicePreset/Device")
            mix = mix[0] if mix is not None and len(mix) else None
            devs = [_wrap_preset(x) for x in _kids(b.find("DevicePresets"))]
            out.append(Chain(val(b, "Name", "") or "", int(val(b, "Color", 0) or 0),
                             [x for x in devs if x is not None], mix, b.find("ZoneSettings")))
        return out
    return Rack(dev, chains_of("BranchPresets"), chains_of("ReturnBranchPresets"))


def racks_in(path, report):
    """Yield (name, top-level object) for everything in the file worth converting."""
    root = read_xml(path)
    stem = Path(path).stem
    gp = root.find("GroupDevicePreset")
    if gp is not None:                                   # .adg
        yield stem, _wrap_preset(gp)
        return
    ap = root.find("AbletonDevicePreset")
    if ap is not None:                                   # .adv (a bare Drift preset, say)
        yield stem, _wrap_preset(ap)
        return
    tracks = root.find("LiveSet/Tracks")                  # .als
    for t in (tracks if tracks is not None else []):
        if t.tag != "MidiTrack":
            continue
        tname = val(t, "Name/EffectiveName", "") or val(t, "Name/UserName", "") or "Track"
        devs = t.find("DeviceChain/DeviceChain/Devices")
        if devs is None or not len(devs):
            continue
        objs = [_wrap_live_device(d) for d in devs]
        first = objs[0]
        name = f"{stem} - {tname}"
        if isinstance(first, Rack):
            rname = val(first.elem, "UserName", "")
            yield (rname or name), first
            if len(objs) > 1:
                report.warn(f"{tname}: devices after the rack on the track are left out "
                            f"(put them inside the rack)")
        else:
            yield name, objs  # bare devices on the track: auto-wrapped below


# ---------------------------------------------------------------- conversion

class Converter:
    def __init__(self, src_path, report):
        self.src = Path(src_path).resolve()
        self.r = report
        self.samples = {}        # bundle path -> source file
        self.original_uris = {}

    # -- parameters
    def params(self, elem, kind, macro_owner=True):
        schema = SCHEMA.get(kind)
        enums = D.ENUMS.get(kind, {})
        out = {}
        if schema is None:
            self.r.error(f"{kind}: Note supports it, but its parameters haven't been learnt "
                         f"yet; run `live2note.py calibrate` once")
            return out
        for key, typ in schema.items():
            if key == "Enabled":
                v = val(elem, "On", "true")
                out[key] = v == "true"
                continue
            m = re.fullmatch(r"Macro(\d)", key)
            if m:
                out[key] = float(val(elem, f"MacroControls.{m.group(1)}", 0))
                continue
            raw = val(elem, key)
            if raw is None:
                self.r.warn(f"{kind}.{key} missing in this Live version's file; Note's default used")
                continue
            if typ == "bool":
                v = raw == "true"
            elif typ == "int":
                v = int(float(raw))
            elif typ == "float":
                v = float(raw)
            else:
                table = enums.get(key)
                i = int(float(raw))
                if not table or i >= len(table):
                    self.r.error(f"{kind}.{key}: Live value {i} has no known Note label")
                    continue
                v = table[i]
                if i not in D.VERIFIED.get((kind, key), {}):
                    self.r.note(f"{kind}.{key} = '{v}' (label from Live's menu order; "
                                f"not yet confirmed by an export)")
            out[key] = self.macro(elem.find(key), v)
        return out

    def macro(self, pelem, v):
        """Carry a rack-macro mapping over. Live stores it on the target parameter as a
        KeyMidi block on hidden channel 16; Note stores {value, macroMapping}."""
        if pelem is None:
            return v
        km = pelem.find("KeyMidi")
        if km is None or val(km, "Channel") != "16" or val(km, "IsNote") == "true":
            return v
        idx = int(val(km, "NoteOrController"))
        if idx > 7:
            self.r.warn(f"macro {idx + 1} drives {pelem.tag}, but Note only has macros 1-8; dropped")
            return v
        rng = pelem.find("MidiControllerRange")
        lo, hi = (float(val(rng, "Min")), float(val(rng, "Max"))) if rng is not None else (0.0, 1.0)
        self.r.note(f"macro {idx + 1} -> {pelem.tag} ({lo:g}..{hi:g})")
        return {"value": v, "macroMapping": {"macroIndex": idx, "rangeMin": lo, "rangeMax": hi}}

    # -- chain mixer
    def mixer(self, m, n_returns=0, is_return=False):
        if m is None:
            return {"pan": 0.0, "solo-cue": False, "speakerOn": True, "volume": 0.0,
                    "sends": [{"isEnabled": not is_return, "amount": -70.0}] * n_returns}
        sends = []
        si = m.find("Sends")
        for s in (si if si is not None else [])[:n_returns]:
            lin = s.find("Send/Manual")
            amt = to_db(lin.get("Value")) if lin is not None else -70.0
            sends.append({"isEnabled": not is_return, "amount": max(amt, -70.0)})
        vol = to_db(val(m, "Volume", 1))
        return {"pan": float(val(m, "Panorama", 0)), "solo-cue": False,
                "speakerOn": val(m, "Speaker", "true") == "true",
                "volume": max(vol, -70.0), "sends": sends}

    # -- devices
    def device(self, obj, depth):
        if isinstance(obj, Rack):
            return self.rack(obj, depth)
        tag = obj.tag
        kind = D.KINDS.get(tag)
        if kind is None:
            hint = D.UNSUPPORTED_HINTS.get(tag, "not available in Note")
            self.r.error(f"{tag}: {hint}")
            return None
        d = {"presetUri": None, "kind": kind, "name": val(obj, "UserName", "") or "",
             "parameters": self.params(obj, kind), "deviceData": {}}
        D.apply_export_rules(kind, d["parameters"])
        if kind == "drift":
            p = d["parameters"]
            vc = D.ENUMS["drift"]["Global_VoiceCount"]
            if vc.index(_plain(p.get("Global_VoiceCount", "4"))) > D.NOTE_MAX_VOICE_COUNT_INDEX:
                self.r.warn(f"Drift voices {_plain(p['Global_VoiceCount'])} -> 8 (Note's maximum)")
                p["Global_VoiceCount"] = "8"
        if kind == "drumCell":
            d["deviceData"]["sampleUri"] = self.sample(obj)
        return d

    def rack(self, rk, depth):
        kind = D.KINDS.get(rk.tag)
        if kind not in ("instrumentRack", "drumRack"):
            self.r.error(f"{rk.tag}: only Instrument Racks and Drum Racks go to Note")
            return None
        d = {"presetUri": None, "kind": kind, "name": "", "parameters": self.params(rk.elem, kind),
             "chains": []}
        if kind == "drumRack":
            d["returnChains"] = []
            if len(rk.chains) > D.NOTE_MAX_PADS:
                self.r.error(f"Drum Rack has {len(rk.chains)} pads; Note plays 16")
            if len(rk.returns) > 1:
                self.r.error(f"Drum Rack has {len(rk.returns)} return chains; Note allows one")
        for ch in rk.chains:
            devs = [self.device(x, depth + 1) for x in ch.devices]
            c = {"name": "", "color": D.chain_color(ch.color), "devices": [x for x in devs if x],
                 "mixer": self.mixer(ch.mixer, len(rk.returns))}
            if kind == "drumRack":
                c["drumZoneSettings"] = self.zone(ch.zone)
            d["chains"].append(c)
        for ch in rk.returns:
            devs = [self.device(x, depth + 1) for x in ch.devices]
            d["returnChains"].append({"name": "", "color": D.chain_color(ch.color),
                                      "devices": [x for x in devs if x],
                                      "mixer": self.mixer(ch.mixer, len(rk.returns), True)})
        return d

    def zone(self, z):
        if z is None:
            return {"receivingNote": 36, "sendingNote": 60, "chokeGroup": None}
        # Live counts pads from the top: ReceivingNote 92 is MIDI note 36.
        choke = int(val(z, "ChokeGroup", 0) or 0)
        return {"receivingNote": 128 - int(val(z, "ReceivingNote", 92)),
                "sendingNote": int(val(z, "SendingNote", 60)),
                "chokeGroup": choke or None}

    # -- samples
    def sample(self, cell):
        fr = cell.find("UserSample/Value/SampleRef/FileRef")
        if fr is None:
            self.r.warn("a Drum Sampler pad has no sample; Note will leave it empty")
            return None
        path, rel = val(fr, "Path", ""), val(fr, "RelativePath", "")
        cands = [Path(path)] if path else []
        if rel:
            cands += [self.src.parent / rel, USER_LIBRARY / rel,
                      self.src.parent.parent / rel]
        name = Path(path or rel).name
        cands += [self.src.parent / "Samples" / "Imported" / name,
                  self.src.parent / "Samples" / name]
        found = next((c for c in cands if c.is_file()), None)
        if found is None:
            self.r.error(f"sample not found: {name} (looked in {len(cands)} places)")
            return None
        key = f"Samples/{found.name}"
        n = 2
        while key in self.samples and self.samples[key] != found:
            key = f"Samples/{found.stem}-{n}{found.suffix}"; n += 1
        self.samples[key] = found
        self.original_uris[key] = found.as_uri()
        return key

    # -- top level
    def preset(self, name, obj):
        if isinstance(obj, list):
            # bare devices on a track (e.g. Drift -> Reverb): wrap in an Instrument Rack,
            # which is what Note wants and what students forget.
            self.r.note("devices were not in a rack: wrapped in an Instrument Rack automatically")
            inner = [self.device(x, 1) for x in obj]
            top = {"kind": "instrumentRack", "name": name,
                   "parameters": {"Enabled": True, **{f"Macro{i}": 0.0 for i in range(8)}},
                   "chains": [{"name": "", "color": 0, "devices": [x for x in inner if x],
                               "mixer": self.mixer(None)}]}
        elif isinstance(obj, Rack) and obj.tag == "DrumGroupDevice":
            self.r.note("bare Drum Rack: wrapped in an Instrument Rack automatically")
            top = {"kind": "instrumentRack", "name": name,
                   "parameters": {"Enabled": True, **{f"Macro{i}": 0.0 for i in range(8)}},
                   "chains": [{"name": "", "color": 0, "devices": [self.rack(obj, 1)],
                               "mixer": self.mixer(None)}]}
        elif isinstance(obj, Rack):
            top = self.rack(obj, 0)
            if top is None:
                return None
            top.pop("presetUri", None)
            top["name"] = name
        else:
            self.r.note("single device: wrapped in an Instrument Rack automatically")
            return self.preset(name, [obj])
        self.shape_check(top)
        return {"$schema": SCHEMA_URL, **top}

    def shape_check(self, top):
        """Note's rules about WHAT goes WHERE (an instrument, then at most a couple of FX)."""
        if len(top["chains"]) != 1:
            self.r.error(f"the outer rack has {len(top['chains'])} chains; Note wants exactly one "
                         f"(layer sounds inside Drift, or make separate presets)")
        if not _sounds(top):
            self.r.error("nothing in it makes sound in Note (needs a Drift, or a Drum Rack "
                         "with Drum Sampler pads)")
        for ch in top["chains"]:
            kinds = [d["kind"] for d in ch["devices"]]
            fx = [k for k in kinds if k in D.EFFECTS]
            if len(fx) > 2:
                self.r.warn(f"{len(fx)} effects after the instrument; Note shows two FX slots")


def _sounds(d):
    if d["kind"] == "drift" or (d["kind"] == "drumCell" and d["deviceData"].get("sampleUri")):
        return True
    return any(_sounds(x) for c in d.get("chains", []) for x in c["devices"])


def _plain(v):
    return v["value"] if isinstance(v, dict) else v


def write_bundle(preset, conv, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    size = sum(p.stat().st_size for p in conv.samples.values())
    if size > D.NOTE_MAX_BUNDLE_BYTES:
        conv.r.error(f"samples total {size >> 20} MB; Note's limit is 400 MB")
        return False
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Preset.ablpreset", json.dumps(preset, indent=2, allow_nan=False,
                                                  default=str))
        z.writestr("BundleInfo.json", json.dumps({"originalSampleUris": conv.original_uris},
                                                 indent=2))
        for key, src in conv.samples.items():
            z.write(src, key)
    return True


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]+', "-", s).strip() or "Preset"


def convert_file(path, outdir, dry=False):
    results = []
    file_report = Report(Path(path).name)
    try:
        items = list(racks_in(path, file_report))
    except (ET.ParseError, OSError, EOFError) as e:
        file_report.error(f"can't read: {e}")
        return [file_report]
    if not items:
        file_report.error("nothing to convert (no MIDI track with an instrument)")
        return [file_report]
    for name, obj in items:
        r = Report(name)
        r.warnings += file_report.warnings
        c = Converter(path, r)
        preset = c.preset(name, obj)
        if preset is not None and not r.errors and not dry:
            out = Path(outdir) / f"{safe_name(name)}.ablpresetbundle"
            if write_bundle(preset, c, out):
                r.note(f"-> {out}")
        results.append(r)
    return results


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("convert", "check"):
        p = sub.add_parser(cmd)
        p.add_argument("files", nargs="+")
        p.add_argument("-o", "--out", default=None)
    w = sub.add_parser("watch")
    w.add_argument("inbox", nargs="?", default=str(USER_LIBRARY / "Presets/Instruments/To Note"))
    w.add_argument("-o", "--out", default=None)
    a = ap.parse_args(argv)

    if a.cmd in ("convert", "check"):
        bad = 0
        for f in a.files:
            outdir = a.out or Path(f).resolve().parent
            for r in convert_file(f, outdir, dry=a.cmd == "check"):
                r.print(); bad += bool(r.errors)
        return 1 if bad else 0

    inbox = Path(a.inbox); inbox.mkdir(parents=True, exist_ok=True)
    out = Path(a.out or inbox / "Note Bundles")
    print(f"watching {inbox}\n  save an Instrument Rack there (or drop .adg/.als in) -> {out}")
    seen = {}
    while True:
        for f in list(inbox.glob("*.adg")) + list(inbox.glob("*.als")):
            m = f.stat().st_mtime
            if seen.get(f) != m and time.time() - m > 1.0:   # let Live finish writing
                seen[f] = m
                for r in convert_file(f, out):
                    r.print()
        time.sleep(1.0)


if __name__ == "__main__":
    sys.exit(main())
