"""What Note's engine accepts, device by device.

Every table here is keyed by Note's JSON parameter name, which is the same as the
XML tag Live writes in an .adg/.als — except that the XML stores choices as indices
and Note stores them as labels. ENUMS turns an index into the label.

Provenance matters, because a wrong label is the one way this tool can produce a
preset Note refuses:
  VERIFIED   — read off a real pair (a rack in an .als  <->  Live's own export of it)
  DOCUMENTED — the menu order in Live's UI / manual; agrees with every VERIFIED entry
               it overlaps, but has not itself been seen in an export.
`calibrate` turns DOCUMENTED into VERIFIED by learning from one export Live makes.
"""

# XML class -> Note "kind". Only kinds Note can load are listed; anything else is
# reported as unsupported (and, for instruments, offered the resample route).
KINDS = {
    "InstrumentGroupDevice": "instrumentRack",
    "DrumGroupDevice": "drumRack",
    "Drift": "drift",
    "DrumCell": "drumCell",
    "Reverb": "reverb",
    "Delay": "delay",
    "Saturator": "saturator",
    # Officially supported by Live's exporter; parameter set not yet seen in an export
    # here, so they convert only after `calibrate` has learnt them.
    "ChannelEq": "channelEq",
    "Chorus2": "chorus",
    "PhaserNew": "phaser",
    "Redux2": "redux2",
}

INSTRUMENTS = {"drift", "drumRack", "drumCell"}
EFFECTS = {"reverb", "delay", "saturator", "channelEq", "chorus", "phaser", "redux2"}

# Well-known things students will reach for, and what to tell them.
UNSUPPORTED_HINTS = {
    "OriginalSimpler": "Simpler: on drum pads use 'Replace Simplers with Drum Sampler'; "
                       "for a melodic sample, resample it (see 'Anything else' in the guide)",
    "MultiSampler": "Sampler isn't in Note: resample it to one note and load it in Melodic Sampler",
    "InstrumentVector": "Wavetable isn't in Live's export list yet: resample it, or rebuild it in Drift",
    "Operator": "Operator isn't in Note: resample it, or rebuild it in Drift",
    "InstrumentMeld": "Meld isn't in Note: resample it",
    "PluginDevice": "Plug-ins can't run on a phone: resample it",
    "AuPluginDevice": "Plug-ins can't run on a phone: resample it",
    "MxDeviceInstrument": "Max for Live can't run in Note: resample it",
    "MxDeviceAudioEffect": "Max for Live can't run in Note: remove it",
    "Eq8": "EQ Eight isn't in Note: use Channel EQ",
    "AutoFilter2": "Auto Filter isn't in Live's export list: remove it",
    "Hybrid": "Hybrid Reverb isn't in Note: use Reverb",
    "Echo": "Echo isn't in Note: use Delay",
    "GlueCompressor": "Glue Compressor isn't in Note: remove it",
    "Compressor2": "Compressor isn't in Live's export list: remove it",
}

_MOD_SOURCES = ["Env 1", "Env 2 / Cyc", "LFO", "Key", "Velocity", "Modwheel", "Pressure", "Slide"]
_RATE_MODES = ["Freq", "Ratio", "Time", "Sync"]

ENUMS = {
    "drift": {
        "Oscillator1_Type": ["Sine", "Triangle", "Shark Tooth", "Saturated", "Saw", "Pulse", "Rectangle"],
        "Oscillator2_Type": ["Sine", "Triangle", "Saturated", "Saw", "Rectangle"],
        "Oscillator1_ShapeModSource": _MOD_SOURCES,
        "Filter_ModSource1": _MOD_SOURCES,
        "Filter_ModSource2": _MOD_SOURCES,
        "Lfo_ModSource": _MOD_SOURCES,
        "PitchModulation_Source1": _MOD_SOURCES,
        "PitchModulation_Source2": _MOD_SOURCES,
        "ModulationMatrix_Source1": _MOD_SOURCES,
        "ModulationMatrix_Source2": _MOD_SOURCES,
        "ModulationMatrix_Source3": _MOD_SOURCES,
        "ModulationMatrix_Target1": None,  # filled below
        "ModulationMatrix_Target2": None,
        "ModulationMatrix_Target3": None,
        "Filter_Type": ["I", "II"],
        "Lfo_Mode": _RATE_MODES,
        "CyclingEnvelope_Mode": _RATE_MODES,
        "Lfo_Shape": ["Sine", "Triangle", "Saw Up", "Saw Down", "Square", "Sample & Hold",
                      "Wander", "Linear Env", "Exponential Env"],
        "Global_Envelope2Mode": ["Env", "Cyc"],
        "Global_VoiceMode": ["Poly", "Mono", "Stereo", "Unison"],
        "Global_VoiceCount": ["4", "8", "12", "16", "20", "24", "28", "32"],
    },
    "drumCell": {
        "Effect_Type": ["Stretch", "Loop", "Pitch Env", "Punch", "8-Bit", "FM", "Ring Mod",
                        "Sub Osc", "Noise"],
        "Voice_Envelope_Mode": ["A-H-D", "A-S-R"],
        "Voice_Filter_Type": ["Highpass", "Lowpass", "Bandpass", "Peak"],
        "Voice_ModulationSource": ["Velocity", "Envelope"],
        "Voice_ModulationTarget": ["Filter", "Pitch", "Volume"],
    },
    "delay": {
        "DelayLine_CompatibilityMode": ["D"],
        "DelayLine_SmoothingMode": ["Repitch", "Fade", "Jump"],
        "DelayLine_SyncedSixteenthL": ["1", "2", "3", "4", "5", "6", "8", "16"],
        "DelayLine_SyncedSixteenthR": ["1", "2", "3", "4", "5", "6", "8", "16"],
        "DryWetMode": ["Linear", "Equal-loudness"],
    },
    "reverb": {
        "HighFilterType": ["Shelf", "Low-pass"],
        "RoomType": ["SuperEco", "Eco", "Mid", "High"],
        "SizeSmoothing": ["None", "Slow", "Fast"],
    },
    "saturator": {
        "Type": ["Analog Clip", "Soft Sine", "Bass Shaper", "Medium Curve", "Hard Curve",
                 "Sinoid Fold", "Digital Clip", "Waveshaper"],
        "PostClip": ["off", "on"],
    },
}
_TARGETS = ["None", "Osc 1 Gain", "Osc 1 Shape", "Osc 2 Gain", "Osc 2 Detune", "Noise Gain",
            "LP Frequency", "LP Resonance", "HP Frequency", "LFO Rate", "Cyc Env Rate", "Main Volume"]
for _i in (1, 2, 3):
    ENUMS["drift"][f"ModulationMatrix_Target{_i}"] = _TARGETS

# (kind, param) -> {index: label} seen in a real Live export. Everything in ENUMS that
# is not here is DOCUMENTED only.
VERIFIED = {
    ("drift", "Oscillator1_Type"): {1: "Triangle", 2: "Shark Tooth", 4: "Saw"},
    ("drift", "Oscillator2_Type"): {2: "Saturated"},
    ("drift", "Filter_Type"): {0: "I", 1: "II"},
    ("drift", "Global_VoiceCount"): {0: "4", 1: "8"},
    ("drift", "Global_VoiceMode"): {0: "Poly"},
    ("drift", "Global_Envelope2Mode"): {0: "Env"},
    ("drift", "Lfo_Mode"): {0: "Freq"},
    ("drift", "CyclingEnvelope_Mode"): {0: "Freq"},
    ("drift", "Lfo_Shape"): {0: "Sine"},
    ("drift", "ModulationMatrix_Target1"): {0: "None", 8: "HP Frequency"},
    **{("drift", p): {1: "Env 2 / Cyc", 2: "LFO", 3: "Key", 4: "Velocity", 5: "Modwheel",
                      6: "Pressure", 7: "Slide"}
       for p in ("Filter_ModSource1", "Filter_ModSource2", "Lfo_ModSource",
                 "Oscillator1_ShapeModSource", "PitchModulation_Source1",
                 "PitchModulation_Source2", "ModulationMatrix_Source1",
                 "ModulationMatrix_Source2", "ModulationMatrix_Source3")},
    ("delay", "DelayLine_SmoothingMode"): {0: "Repitch", 1: "Fade"},
    ("delay", "DelayLine_SyncedSixteenthL"): {5: "6"},
    ("delay", "DelayLine_SyncedSixteenthR"): {3: "4"},
    ("delay", "DryWetMode"): {1: "Equal-loudness"},
    ("delay", "DelayLine_CompatibilityMode"): {0: "D"},
    ("drumCell", "Effect_Type"): {0: "Stretch"},
    ("drumCell", "Voice_Envelope_Mode"): {0: "A-H-D"},
    ("drumCell", "Voice_Filter_Type"): {1: "Lowpass"},
    ("drumCell", "Voice_ModulationSource"): {0: "Velocity"},
    ("drumCell", "Voice_ModulationTarget"): {0: "Filter"},
}

# Note's polyphony ceiling for Drift (Live allows 32). Index into Global_VoiceCount.
NOTE_MAX_VOICE_COUNT_INDEX = 1  # "8"
NOTE_MAX_PADS = 16
NOTE_MAX_BUNDLE_BYTES = 400 * 1024 * 1024


def apply_export_rules(kind, p):
    """What Live's own exporter changes on the way to Note — observed identically on every
    rack/export pair (6 Drift racks). Mostly CPU: Note runs on a phone."""
    def setv(k, v):
        if k in p:
            p[k] = {**p[k], "value": v} if isinstance(p[k], dict) else v
    def getv(k):
        x = p.get(k)
        return x["value"] if isinstance(x, dict) else x
    if kind == "drift":
        setv("Global_HiQuality", False)
    elif kind == "reverb":
        setv("RoomType", "SuperEco")
        # Note's Reverb has its low shelf always in; "off" is exported as "on at unity".
        if getv("ShelfLowOn") is False:
            setv("ShelfLowOn", True); setv("ShelfLoGain", 1.0)
        if getv("ShelfHighOn") is False:          # by symmetry; not yet seen in an export
            setv("ShelfHighOn", True); setv("ShelfHiGain", 1.0)
    elif kind == "delay":
        setv("DelayLine_Link", True)
        setv("EcoProcessing", True)


def chain_color(live_color):
    """Live chain colour index -> Note's. Seen: 4->8, 12->24 (Note's palette is indexed at
    twice the step). Anything that would fall off the end is kept as is."""
    c = int(live_color) * 2
    return c if c < 70 else int(live_color)
