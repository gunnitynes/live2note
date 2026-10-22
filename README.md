# live2note

Turns Live instruments into Ableton Note presets (`.ablpresetbundle`) without the hidden
`-_Feature.ExportPresetsToAbl` flag or the right-click export.

## Why it works

An `.ablpresetbundle` is a zip holding `Preset.ablpreset` (JSON), `BundleInfo.json` and
`Samples/`. Live's `.adg`/`.als` are gzipped XML, and **the XML parameter names are Note's
JSON names**. The differences are:

- choices are stored as indices in Live and as labels in Note (`devices.py` ENUMS)
- Live's exporter applies a few phone-CPU overrides (Drift HiQuality off, Reverb SuperEco,
  Delay eco + linked; `apply_export_rules`)
- drum pads count notes from the top (`receivingNote = 128 - ReceivingNote`), chain volume
  is linear in Live and dB in Note, chain colours are doubled
- a macro mapping lives on the target parameter as a channel-16 `KeyMidi`; Note stores it as
  `{value, macroMapping:{macroIndex, rangeMin, rangeMax}}` (Live's own exporter drops these)

## Verified

- `tests/roundtrip.py`: rebuilds every bundle Live exported on the T7 drive from its source
  rack. All 7 bundles whose source rack was still saved come out **identical** to Live's
  export (6 Drift + Reverb + Delay, 1 Drum Rack with Drum Sampler).
- `tests/parity.mjs`: the browser converter and the Python one give the same output for all
  114 racks in those sets.
- Not yet verified: loading a bundle on the phone (try `phone-test/`), the labels marked
  "from Live's menu order", and Chorus / Phaser / Redux / Channel EQ (not yet seen in an export).

## Use

Students: **https://gunnitynes.github.io/live2note/** (the same page as `docs/index.html`;
nothing is uploaded, it all runs in the browser).
Drop an `.adg`, or a Live project folder after **File → Collect All and Save**.

Teacher / batch:

    python3 live2note.py check  Set.als            # what would fail, and why
    python3 live2note.py convert Rack.adg Set.als -o out/
    python3 live2note.py watch                      # converts racks saved into
                                                    # User Library/Presets/Instruments/To Note

After editing `devices.py`, `core.js` or `page.html`, run `python3 build_web.py`.
