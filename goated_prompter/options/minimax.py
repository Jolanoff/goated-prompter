"""MiniMax H3 models, generation modes, aspect ratios and per-modality reference limits."""

MODELS = ("MiniMax H3",)
MODES = ("auto", "T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA")
RATIOS = ("Auto", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9")
LIMITS = {"image": 9, "video": 3, "audio": 3}
