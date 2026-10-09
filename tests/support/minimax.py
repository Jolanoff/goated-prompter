"""Fixed MiniMax reference examples and its session-aware scripted backend."""

from contextlib import contextmanager
import json
import threading

from goated_prompter.backends.base import GoatedPrompterBackend
from goated_prompter.minimax import validate_minimax_draft

REQUEST = ("I want the person in <image1> to do the same dancing style and movements as the dancer in <video1>. "
           "Put the person on a rooftop at night with neon city lights behind them. I want energetic electronic music. "
           "Start with a medium full-body shot, then slowly move the camera around the dancer.")
BASE = "integrated_multimodal_description: [Shot 1] A leaf falls onto a quiet path.\n\noverall_soundscape: Wind rustles the branches.\n\nnon_diegetic_music: N/A"
REF = """subject_definitions:
<Subject 1> is the person shown in <Picture 1>, preserving the person's visible identity, appearance and clothing.
<Subject 2> is the dance performance in <Video 1>, supplying only body movement, timing and pose transitions for <Subject 1>.

summary:
[reference generation] <Subject 1> performs the movement of <Subject 2> on a rooftop at night, with neon city lights behind them, in a continuous 15-second shot.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - retain the target person's visible identity, appearance and clothing.
<Subject 2> (appears in [Shot 1]): attribute_transfer - transfer the dance to <Subject 1>, excluding the source dancer's appearance, clothing, environment, camera, lighting and audio.

detailed_description:
The target video uses live-action cinematography on a neon-lit nighttime rooftop.
[Shot 1] A medium full-body composition centers <Subject 1>, with room around their arms and feet for the dance movement supplied by <Subject 2>. The rooftop floor establishes a stable contact plane beneath the dancer, while neon city lights remain behind them. Begin the referenced movement without changing the target person's identity or importing the source video's setting. Over the 15-second clip, the body follows the reference's movement character and pose transitions in a continuous progression, adapting the performed phrase to the available duration rather than squeezing in extra routines. Foot contacts remain grounded as weight shifts follow the referenced performance. The camera arcs slowly around <Subject 1>, keeping their full body in frame while the distant city lights shift gradually in perspective. Let the camera movement remain subordinate to the dance; do not inherit camera motion or framing from the motion source. Rooftop wind and foot contacts stay synchronized with the physical action. As the clip reaches its end, settle the camera into a clear full-body view while the selected movement phrase reaches its natural ending state.

overall_soundscape:
Rooftop wind continues beneath synchronized foot contacts and subtle fabric movement. Distant city traffic remains low in the background.

non_diegetic_music:
Generate an energetic electronic score with a brisk four-on-the-floor kick, crisp hi-hats and a pulsing synthesizer bass. Introduce a bright synth phrase as the dance develops, then resolve it at the 15-second ending without copying reference audio."""


def role(token, *roles):
    return {"token": token, "roles": list(roles), "target": "target person", "transfer": "requested role only",
            "exclude": "unrequested appearance, environment, camera, light and audio"}


def plan_json(*items, first=None, last=None):
    return json.dumps({"references": items, "first_frame": first, "last_frame": last})


DANCE_PLAN = plan_json(role("image1", "identity", "appearance"), role("video1", "dance", "motion"))


def dance_input(**overrides):
    return validate_minimax_draft({"references": ["image1", "video1"], "duration_seconds": 15,
                                  "planning_mode": "Direct",  # Freeze the pre-planning writer/repair contract.
                                  "user_request": REQUEST, **overrides}, generation=True)


class ScriptedBackend(GoatedPrompterBackend):
    name = "scripted"

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        self.sessions = self.exits = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False

    @contextmanager
    def generation_session(self):
        self.sessions += 1
        try:
            yield self
        finally:
            self.exits += 1

    def generate(self, instruction):
        self.calls.append(instruction)
        self.entered.set()
        if self.block and not self.release.wait(5):
            raise ValueError("Test timeout")
        return next(self.responses)
