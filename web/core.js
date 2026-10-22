// live2note core — the same converter as live2note.py, for the browser (and Node, for tests).
// Input: the XML text of an .adg / .adv / .als. Output: presets + a report per preset.
// Samples are resolved through a callback, because only the caller knows what files it has.
(function (root) {
  "use strict";
  let T = null; // tables: kinds, enums, schema, verified, hints (from devices.py)

  // ------------------------------------------------------------ tiny XML parser
  // Live's XML is attributes-only elements; text nodes carry nothing we need.
  function parseXML(s) {
    const re = /<(\/?)([A-Za-z_][\w.\-]*)((?:\s+[\w.\-:]+="[^"]*")*)\s*(\/?)>|<\?[^>]*\?>|<!--[\s\S]*?-->/g;
    const attrRe = /([\w.\-:]+)="([^"]*)"/g;
    const top = { tag: "#doc", a: {}, c: [] };
    const stack = [top];
    let m;
    while ((m = re.exec(s))) {
      if (!m[2]) continue; // declaration/comment
      if (m[1]) { stack.pop(); continue; }
      const el = { tag: m[2], a: {}, c: [] };
      let am; attrRe.lastIndex = 0;
      while ((am = attrRe.exec(m[3]))) el.a[am[1]] = unesc(am[2]);
      stack[stack.length - 1].c.push(el);
      if (!m[4]) stack.push(el);
    }
    return top.c[0];
  }
  function unesc(v) {
    return v.indexOf("&") < 0 ? v : v.replace(/&lt;/g, "<").replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, "&");
  }
  const find = (e, path) => {
    if (!e) return null;
    for (const p of path.split("/")) {
      e = e.c.find((x) => x.tag === p);
      if (!e) return null;
    }
    return e;
  };
  const kids = (e) => (e ? e.c : []);
  function* iter(e, tag) {
    if (e.tag === tag) yield e;
    for (const c of e.c) yield* iter(c, tag);
  }
  function val(e, name, dflt) {
    const c = find(e, name);
    if (!c) return dflt;
    const m = find(c, "Manual");
    const v = (m || c).a.Value;
    return v === undefined ? dflt : v;
  }
  // Live writes float fields as 127.0, never 127. Float-typed values are boxed in F so the
  // serializer can do the same; nothing else in the converter needs to know.
  class F { constructor(v) { this.v = v; } valueOf() { return this.v; } }
  const f = (v) => new F(+v);
  const toDb = (lin) => (+lin <= 0 ? -Infinity : 20 * Math.log10(+lin));

  // ------------------------------------------------------------ report
  class Report {
    constructor(name) { this.name = name; this.errors = []; this.warnings = []; this.notes = []; }
    error(m) { this.errors.push(m); } warn(m) { this.warnings.push(m); } note(m) { this.notes.push(m); }
  }

  // ------------------------------------------------------------ two layouts -> one shape
  const RACKS = new Set(["InstrumentGroupDevice", "DrumGroupDevice", "AudioEffectGroupDevice"]);
  function devicesInChain(b) {
    const dc = find(b, "DeviceChain");
    let devs = null;
    if (dc) for (const d of iter(dc, "Devices")) { devs = d; break; }
    return kids(devs).map(wrapLive);
  }
  function wrapLive(d) {
    if (!RACKS.has(d.tag)) return d;
    return {
      rack: true, tag: d.tag, elem: d,
      chains: kids(find(d, "Branches")).map((b) => ({
        color: +val(b, "Color", 0) || 0, devices: devicesInChain(b),
        mixer: find(b, "MixerDevice"), zone: find(b, "BranchInfo") })),
      returns: kids(find(d, "ReturnBranches")).map((b) => ({
        color: +val(b, "Color", 0) || 0, devices: devicesInChain(b), mixer: find(b, "MixerDevice") })),
    };
  }
  function wrapPreset(p) {
    const devWrap = find(p, "Device");
    const dev = devWrap && devWrap.c[0];
    if (p.tag !== "GroupDevicePreset") return dev || null;
    const chainsOf = (tag) => kids(find(p, tag)).map((b) => {
      const mw = find(b, "MixerPreset/AbletonDevicePreset/Device");
      return { color: +val(b, "Color", 0) || 0,
        devices: kids(find(b, "DevicePresets")).map(wrapPreset).filter(Boolean),
        mixer: mw && mw.c[0], zone: find(b, "ZoneSettings") };
    });
    return { rack: true, tag: dev.tag, elem: dev, chains: chainsOf("BranchPresets"),
      returns: chainsOf("ReturnBranchPresets") };
  }
  function racksIn(xmlText, stem, fileReport) {
    const r = parseXML(xmlText);
    const gp = find(r, "GroupDevicePreset");
    if (gp) return [[stem, wrapPreset(gp)]];
    const ap = find(r, "AbletonDevicePreset");
    if (ap) return [[stem, wrapPreset(ap)]];
    const out = [];
    for (const t of kids(find(r, "LiveSet/Tracks"))) {
      if (t.tag !== "MidiTrack") continue;
      const tname = val(t, "Name/EffectiveName", "") || val(t, "Name/UserName", "") || "Track";
      const devs = kids(find(t, "DeviceChain/DeviceChain/Devices"));
      if (!devs.length) continue;
      const objs = devs.map(wrapLive);
      const first = objs[0];
      if (first.rack) {
        out.push([val(first.elem, "UserName", "") || `${stem} - ${tname}`, first]);
        if (objs.length > 1) fileReport.warn(`${tname}: devices after the rack on the track are left out (put them inside the rack)`);
      } else out.push([`${stem} - ${tname}`, objs]);
    }
    return out;
  }

  // ------------------------------------------------------------ conversion
  const plain = (v) => (v instanceof F ? v.v : v && typeof v === "object" ? v.value : v);

  class Converter {
    constructor(report, resolveSample) {
      this.r = report; this.resolve = resolveSample;
      this.samples = new Map(); this.originalUris = {};
    }
    params(elem, kind) {
      const schema = T.schema[kind], enums = T.enums[kind] || {};
      const out = {};
      if (!schema) {
        this.r.error(`${kind}: Note supports it, but this tool hasn't learnt its settings yet`);
        return out;
      }
      for (const [key, typ] of Object.entries(schema)) {
        if (key === "Enabled") { out[key] = val(elem, "On", "true") === "true"; continue; }
        const mm = /^Macro(\d)$/.exec(key);
        if (mm) { out[key] = f(val(elem, `MacroControls.${mm[1]}`, 0)); continue; }
        const raw = val(elem, key);
        if (raw === undefined) { this.r.warn(`${kind}.${key} missing in this Live version's file; Note's default used`); continue; }
        let v;
        if (typ === "bool") v = raw === "true";
        else if (typ === "int") v = Math.trunc(+raw);
        else if (typ === "float") v = f(raw);
        else {
          const table = enums[key], i = Math.trunc(+raw);
          if (!table || i >= table.length) { this.r.error(`${kind}.${key}: Live value ${i} has no known Note label`); continue; }
          v = table[i];
          const ver = T.verified[`${kind}.${key}`] || [];
          if (!ver.includes(i)) this.r.note(`${kind}.${key} = '${v}' (label from Live's menu order; not yet confirmed by an export)`);
        }
        out[key] = this.macro(find(elem, key), v);
      }
      return out;
    }
    macro(pe, v) {
      const km = pe && find(pe, "KeyMidi");
      if (!km || val(km, "Channel") !== "16" || val(km, "IsNote") === "true") return v;
      const idx = +val(km, "NoteOrController");
      if (idx > 7) { this.r.warn(`macro ${idx + 1} drives ${pe.tag}, but Note only has macros 1-8; dropped`); return v; }
      const rng = find(pe, "MidiControllerRange");
      const lo = rng ? +val(rng, "Min") : 0, hi = rng ? +val(rng, "Max") : 1;
      this.r.note(`macro ${idx + 1} -> ${pe.tag} (${lo}..${hi})`);
      return { value: v, macroMapping: { macroIndex: idx, rangeMin: f(lo), rangeMax: f(hi) } };
    }
    mixer(m, nReturns = 0, isReturn = false) {
      if (!m) return { pan: f(0), "solo-cue": false, speakerOn: true, volume: f(0),
        sends: Array.from({ length: nReturns }, () => ({ isEnabled: !isReturn, amount: f(-70) })) };
      const sends = kids(find(m, "Sends")).slice(0, nReturns).map((s) => {
        const lin = find(s, "Send/Manual");
        const amt = lin ? toDb(lin.a.Value) : -70;
        return { isEnabled: !isReturn, amount: f(Math.max(amt, -70)) };
      });
      return { pan: f(val(m, "Panorama", 0)), "solo-cue": false, speakerOn: val(m, "Speaker", "true") === "true",
        volume: f(Math.max(toDb(val(m, "Volume", 1)), -70)), sends };
    }
    device(obj) {
      if (obj.rack) return this.rack(obj);
      const kind = T.kinds[obj.tag];
      if (!kind) { this.r.error(`${obj.tag}: ${T.hints[obj.tag] || "not available in Note"}`); return null; }
      const d = { presetUri: null, kind, name: val(obj, "UserName", "") || "", parameters: this.params(obj, kind), deviceData: {} };
      applyExportRules(kind, d.parameters);
      if (kind === "drift") {
        const vc = T.enums.drift.Global_VoiceCount;
        const cur = plain(d.parameters.Global_VoiceCount);
        if (cur !== undefined && vc.indexOf(cur) > 1) {
          this.r.warn(`Drift voices ${cur} -> 8 (Note's maximum)`);
          d.parameters.Global_VoiceCount = "8";
        }
      }
      if (kind === "drumCell") d.deviceData.sampleUri = this.sample(obj);
      return d;
    }
    rack(rk) {
      const kind = T.kinds[rk.tag];
      if (kind !== "instrumentRack" && kind !== "drumRack") { this.r.error(`${rk.tag}: only Instrument Racks and Drum Racks go to Note`); return null; }
      const d = { presetUri: null, kind, name: "", parameters: this.params(rk.elem, kind), chains: [] };
      if (kind === "drumRack") {
        d.returnChains = [];
        if (rk.chains.length > 16) this.r.error(`Drum Rack has ${rk.chains.length} pads; Note plays 16`);
        if (rk.returns.length > 1) this.r.error(`Drum Rack has ${rk.returns.length} return chains; Note allows one`);
      }
      for (const ch of rk.chains) {
        const c = { name: "", color: chainColor(ch.color), devices: ch.devices.map((x) => this.device(x)).filter(Boolean),
          mixer: this.mixer(ch.mixer, rk.returns.length) };
        if (kind === "drumRack") c.drumZoneSettings = zone(ch.zone);
        d.chains.push(c);
      }
      for (const ch of rk.returns)
        d.returnChains.push({ name: "", color: chainColor(ch.color), devices: ch.devices.map((x) => this.device(x)).filter(Boolean),
          mixer: this.mixer(ch.mixer, rk.returns.length, true) });
      return d;
    }
    sample(cell) {
      const fr = find(cell, "UserSample/Value/SampleRef/FileRef");
      if (!fr) { this.r.warn("a Drum Sampler pad has no sample; Note will leave it empty"); return null; }
      const path = val(fr, "Path", ""), rel = val(fr, "RelativePath", "");
      const name = (path || rel).split("/").pop();
      const hit = this.resolve({ path, rel, name });
      if (!hit) { this.r.error(`sample not found: ${name}`); return null; }
      let key = `Samples/${hit.name}`, n = 2;
      while (this.samples.has(key) && this.samples.get(key).id !== hit.id) {
        const dot = hit.name.lastIndexOf(".");
        key = `Samples/${hit.name.slice(0, dot)}-${n++}${hit.name.slice(dot)}`;
      }
      this.samples.set(key, hit);
      this.originalUris[key] = hit.uri || "file://" + encodeURI(path || rel);
      return key;
    }
    preset(name, obj) {
      const wrap = (devs, why) => {
        this.r.note(why);
        return { kind: "instrumentRack", name,
          parameters: Object.assign({ Enabled: true }, ...[0, 1, 2, 3, 4, 5, 6, 7].map((i) => ({ [`Macro${i}`]: f(0) }))),
          chains: [{ name: "", color: 0, devices: devs.filter(Boolean), mixer: this.mixer(null) }] };
      };
      let top;
      if (Array.isArray(obj)) top = wrap(obj.map((x) => this.device(x)), "devices were not in a rack: wrapped in an Instrument Rack automatically");
      else if (obj.rack && obj.tag === "DrumGroupDevice") top = wrap([this.rack(obj)], "bare Drum Rack: wrapped in an Instrument Rack automatically");
      else if (obj.rack) { top = this.rack(obj); if (!top) return null; delete top.presetUri; top.name = name; }
      else return this.preset(name, [obj]);
      if (top.chains.length !== 1)
        this.r.error(`the outer rack has ${top.chains.length} chains; Note wants exactly one (make separate presets)`);
      if (!sounds(top)) this.r.error("nothing in it makes sound in Note (needs a Drift, or a Drum Rack with Drum Sampler pads)");
      for (const ch of top.chains) {
        const fx = ch.devices.filter((d) => T.effects.includes(d.kind));
        if (fx.length > 2) this.r.warn(`${fx.length} effects after the instrument; Note shows two FX slots`);
      }
      return Object.assign({ $schema: "http://tech.ableton.com/schema/song/1.7.0/devicePreset.json" }, top);
    }
  }
  function sounds(d) {
    if (d.kind === "drift" || (d.kind === "drumCell" && d.deviceData.sampleUri)) return true;
    return (d.chains || []).some((c) => c.devices.some(sounds));
  }
  function zone(z) {
    if (!z) return { receivingNote: 36, sendingNote: 60, chokeGroup: null };
    const choke = +val(z, "ChokeGroup", 0) || 0;
    return { receivingNote: 128 - +val(z, "ReceivingNote", 92), sendingNote: +val(z, "SendingNote", 60), chokeGroup: choke || null };
  }
  function chainColor(c) { const x = c * 2; return x < 70 ? x : c; }
  function applyExportRules(kind, p) {
    const set = (k, v) => { if (k in p) p[k] = p[k] && typeof p[k] === "object" && !(p[k] instanceof F) ? { ...p[k], value: v } : v; };
    if (kind === "drift") set("Global_HiQuality", false);
    else if (kind === "reverb") {
      set("RoomType", "SuperEco");
      if (plain(p.ShelfLowOn) === false) { set("ShelfLowOn", true); set("ShelfLoGain", f(1)); }
      if (plain(p.ShelfHighOn) === false) { set("ShelfHighOn", true); set("ShelfHiGain", f(1)); }
    } else if (kind === "delay") { set("DelayLine_Link", true); set("EcoProcessing", true); }
  }

  // Python's json.dumps writes 1.0 for floats; JS writes 1. Both are the same JSON number.
  function convert(xmlText, stem, resolveSample) {
    const fileReport = new Report(stem);
    let items;
    try { items = racksIn(xmlText, stem, fileReport); }
    catch (e) { fileReport.error(`can't read: ${e.message}`); return [{ report: fileReport }]; }
    if (!items.length) { fileReport.error("nothing to convert (no MIDI track with an instrument)"); return [{ report: fileReport }]; }
    return items.map(([name, obj]) => {
      const r = new Report(name);
      r.warnings.push(...fileReport.warnings);
      const c = new Converter(r, resolveSample);
      const preset = c.preset(name, obj);
      return { report: r, preset, samples: c.samples, bundleInfo: { originalSampleUris: c.originalUris } };
    });
  }

  // ------------------------------------------------------------ zip (stored, no compression)
  const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
  function crc32(b) { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; }
  function zip(files) { // files: [[name, Uint8Array]]
    const enc = new TextEncoder(), parts = [], central = [];
    let off = 0;
    for (const [name, data] of files) {
      const nb = enc.encode(name), crc = crc32(data);
      const h = new DataView(new ArrayBuffer(30));
      h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint16(6, 0x0800, true);
      h.setUint16(8, 0, true); h.setUint16(10, 0, true); h.setUint16(12, 0x21, true);
      h.setUint32(14, crc, true); h.setUint32(18, data.length, true); h.setUint32(22, data.length, true);
      h.setUint16(26, nb.length, true); h.setUint16(28, 0, true);
      parts.push(new Uint8Array(h.buffer), nb, data);
      const cd = new DataView(new ArrayBuffer(46));
      cd.setUint32(0, 0x02014b50, true); cd.setUint16(4, 20, true); cd.setUint16(6, 20, true); cd.setUint16(8, 0x0800, true);
      cd.setUint16(10, 0, true); cd.setUint16(12, 0, true); cd.setUint16(14, 0x21, true);
      cd.setUint32(16, crc, true); cd.setUint32(20, data.length, true); cd.setUint32(24, data.length, true);
      cd.setUint16(28, nb.length, true); cd.setUint32(42, off, true);
      central.push(new Uint8Array(cd.buffer), nb);
      off += 30 + nb.length + data.length;
    }
    const cdSize = central.reduce((s, x) => s + x.length, 0);
    const e = new DataView(new ArrayBuffer(22));
    e.setUint32(0, 0x06054b50, true); e.setUint16(8, files.length, true); e.setUint16(10, files.length, true);
    e.setUint32(12, cdSize, true); e.setUint32(16, off, true);
    return new Blob([...parts, ...central, new Uint8Array(e.buffer)], { type: "application/zip" });
  }
  function jsonText(x, ind = "") {
    const pad = ind + "  ";
    if (x instanceof F) {
      const v = Number.isFinite(x.v) ? x.v : -70;
      return Number.isInteger(v) ? v.toFixed(1) : String(v);
    }
    if (x === null || typeof x !== "object") return JSON.stringify(x === -Infinity ? -70 : x);
    if (Array.isArray(x)) return x.length ? "[\n" + x.map((v) => pad + jsonText(v, pad)).join(",\n") + "\n" + ind + "]" : "[]";
    const ks = Object.keys(x).filter((k) => x[k] !== undefined);
    return ks.length ? "{\n" + ks.map((k) => pad + JSON.stringify(k) + ": " + jsonText(x[k], pad)).join(",\n") + "\n" + ind + "}" : "{}";
  }
  function bundle(result, sampleBytes) { // sampleBytes: Map key -> Uint8Array
    const enc = new TextEncoder();
    const files = [["Preset.ablpreset", enc.encode(jsonText(result.preset))],
      ["BundleInfo.json", enc.encode(jsonText(result.bundleInfo))]];
    for (const [k, b] of sampleBytes) files.push([k, b]);
    return zip(files);
  }

  root.Live2Note = { setTables: (t) => (T = t), convert, bundle, jsonText, parseXML, crc32 };
})(typeof window !== "undefined" ? window : globalThis);
