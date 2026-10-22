import fs from "fs"; import zlib from "zlib"; import path from "path";
const P = process.argv[2];
await import(path.resolve("web/core.js"));
const L = globalThis.Live2Note;
L.setTables(JSON.parse(fs.readFileSync("web_tables.json")));
const files = JSON.parse(fs.readFileSync(P + "/files.json"));
let same = 0, diff = 0;
const norm = (x) => JSON.parse(x === null ? "null" : typeof x === "string" ? x : L.jsonText(x));
const eq = (a, b) => {
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a));
  if (a && b && typeof a === "object") { const ka = Object.keys(a), kb = Object.keys(b);
    if (ka.length !== kb.length) return false; return ka.every((k) => eq(a[k], b[k])); }
  return a === b;
};
files.forEach((f, i) => {
  const xml = zlib.gunzipSync(fs.readFileSync(f)).toString("utf8");
  const res = L.convert(xml, path.basename(f, ".als"), ({ name }) => ({ id: name, name }));
  res.forEach((r, j) => {
    const pyf = `${P}/py/${i}_${j}.json`;
    if (!fs.existsSync(pyf)) { console.log("only in js", f, j); diff++; return; }
    const py = JSON.parse(fs.readFileSync(pyf));
    const ok = eq(JSON.parse(JSON.stringify(py.preset, (k,v)=>v===-Infinity||v==="-Infinity"?-70:v)), norm(r.preset ?? null)) && py.errors === r.report.errors.length;
    ok ? same++ : diff++;
    if (!ok) console.log("DIFF", path.basename(f), j, r.report.name, py.errors, r.report.errors.length,
      JSON.stringify(norm(r.preset)).slice(0, 0));
  });
});
console.log(`parity: ${same} identical, ${diff} different`);
