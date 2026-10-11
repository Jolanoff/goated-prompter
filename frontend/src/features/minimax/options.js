// MiniMax H3 models, generation modes, aspect ratios and per-modality reference limits.
// Keep in sync with goated_prompter/options/minimax.py (checked by tests/unit/shared/test_option_parity.py).

export const modes = [["auto", "Auto"], ["T2VA", "Text to Video"], ["I2VA", "First Frame"],
  ["FL2VA", "First + Last Frame"], ["L2VA", "Last Frame"], ["Ref2VA", "Full Reference"]];

export const models = ["MiniMax H3"];

export const ratios = ["Auto", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"];

export const referenceLimits = { image: 9, video: 3, audio: 3 };
