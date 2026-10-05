<a id="top"></a>

<div align="center">

# 🐐 Goated Prompter

**From rough idea to ready-to-use prompt.**

A local prompt studio for image and video workflows.<br>
Bring your ideas and reference images. Shape the result. Copy it into your favorite generator.

[![License: Source Available](https://img.shields.io/badge/License-Source_Available-a3e635?style=flat-square)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=white)](frontend/package.json)
[![llama.cpp](https://img.shields.io/badge/Local_inference-llama.cpp-a3e635?style=flat-square)](https://github.com/ggml-org/llama.cpp)

[Get started](#installation) · [Workflows](#using-the-controls) · [Troubleshooting](#troubleshooting) · [Development](#development-and-verification) · [Architecture](docs/refactoring.md) · [Report an issue](https://github.com/Jolanoff/goated-prompter/issues)

</div>

---

Goated Prompter pairs a **React + Tailwind interface** with a **Python backend** and a language/vision model. Control the task, target model, creativity, detail, and exactly which parts of your references to preserve—all from your browser.

> [!NOTE]
> **This app writes prompts, not images or videos.** Copy the output into your preferred generation tool. Model weights are downloaded separately.

## Features

| Workflow | What you can do |
| --- | --- |
| **Prompt Builder** | Turn text and up to **four reference images** into target-aware prompts. Mix a face from one image, a pose from another, and lighting from a third. |
| **Refine & history** | Make targeted edits, lock important details, compare changes, and explore branching versions with persistent undo/redo. |
| **MiniMax H3** | Write video prompts for **4–15-second clips**, with symbolic references, automatic role analysis, H3 schemas, and Director presets. |
| **Dataset** | Create **1–25 prompts** from a shared concept, with trigger controls, scene planning, quality checks, and TXT/JSONL export. |
| **Saved Prompts** | Keep a named prompt library, reuse instruction presets, and pick up where you left off with autosaved drafts. |

- **Your creative direction:** photography, architecture, characters, products, image editing, style transfer, dataset captions, and video shots.
- **Your inference setup:** managed local **llama.cpp** or an **OpenAI-compatible endpoint**, with shared generation controls and local job cancellation.
- **Your workspace:** responsive, dark by default, with an optional light theme and persistent creative settings.

### Supported targets

**Images:** Generic · Anima · Krea 2 · FLUX.2 Klein · Z-Image Base · Z-Image Turbo · Qwen Image (original Qwen/Qwen-Image checkpoint) · Qwen Image 2.1 · Ideogram4<br>
**Video:** MiniMax H3 · LTX 2.5

Target adapters own structure, syntax and useful density envelopes. Length changes descriptive density inside that envelope; creativity changes semantic invention, never serialization. Krea preserves non-photographic media, Klein stays moderately detailed, and LTX uses a focused chronological paragraph without inventing dialogue, camera movement or cuts. Anima supports lowercase-style tags, appropriate quality/score tags and scene prose; negative conditioning stays separate. Ideogram validates ordered JSON keys, normalized bounds and uppercase hex colors while retaining literal text. Lightweight capability metadata lives in `goated_prompter/prompting/target_models.py`. Saved legacy target names migrate to the clarified names.

The former Maximum Detail and Krea High Detail Directors are repurposed as **Technical Visual Precision** and **Krea 2 Visual Precision**, retaining their stable IDs without controlling verbosity. Krea-specific Directors are inactive on unrelated targets. **Krea 2 Identity Edit v1.2 (Community)** describes the community model/workflow, not an official Krea.ai base capability. The single **MiniMax H3 Director** supplies creative staging and continuity, not target serialization; both former MiniMax preset IDs remain compatible.

The **target model** shapes the writing instructions and output format. The **prompt engine** is the language/vision model that writes the text. Selecting a target does not download or run that image/video generator.

<details>
<summary><strong>Qwen Image 2.1: output format and generation limits</strong></summary>

Qwen Image 2.1 uses writing guidance from the official [text-to-image](https://github.com/QwenLM/Qwen-Image-2.1/blob/main/prompt_rewrite/prompts/system_prompt_t2i.txt) and [image-editing](https://github.com/QwenLM/Qwen-Image-2.1/blob/main/prompt_rewrite/prompts/system_prompt_edit.txt) prompts, with **plain prompt text** as the app's output:

- **Text only:** an observer-style description of the finished image.
- **Selected image references:** an actionable editing directive grounded in the selected image evidence.

JSON metadata is not required. If a model still returns the upstream JSON envelope, the app extracts `rewritten_prompt` for editing, copying and saving.

All Qwen Image 2.1 detail levels (Short, Medium, Detailed and Maximum Detail) use uncapped requests in Builder, Refine and format repairs. Length controls writing detail inside the observer adapter's useful envelope rather than cutting off output. Local llama.cpp receives `max_tokens: -1`; remote requests omit `max_tokens`. Model context capacity and server-side limits still apply.

</details>

<details>
<summary><strong>MiniMax H3: references, clip timing, and output validation</strong></summary>

Open **MiniMax H3**, choose **Clip Length** (10 seconds by default), leave **Mode** on Auto, and describe your video. Choose **MiniMax H3 Director** or any existing instruction preset for creative direction.

Use **+ Image**, **+ Video**, and **+ Audio** to insert symbolic tokens at the cursor. Clicking a chip inserts it again. Valid tokens typed directly into the request are also registered; their numbers stay stable. Example:

```text
The person in <image1> performs the dance movements from <video1> on a neon-lit rooftop at night. Use energetic electronic music and slowly orbit the camera around the dancer.
```

Auto distinguishes identity/motion/style references from explicit first/last-frame anchors. The prompt engine internally analyzes each reference's role, then writes the appropriate base or six-section full-reference prompt. It receives only text, so instructions prohibit inventing unseen media contents. Requested music is generated unless you explicitly ask to copy reference audio.

- Images: up to 9; videos: up to 3; audio: up to 3; 12 combined assets, per the official H3 limits. Audio-only references show a non-blocking compatibility warning.
- **Generate** and **Regenerate** use the existing prompt engine. **Copy** includes the complete editable output. **Clear** resets the request, result, and reference set while keeping scene settings.
- Settings, references, request, and edited output autosave independently in `workflow_settings.json`. Shared job controls support cancellation.
- Local prompting knowledge and source links live in [`goated_prompter/minimax_knowledge`](goated_prompter/minimax_knowledge/SOURCES.md). No documentation fetch is needed during generation.
- Output validation checks H3 section order, exact frame alignment, shot timing, reference IDs, retention markers and dialogue syntax before delivery. Invalid output gets one repair attempt; a failed attempt leaves your previous output intact.
- MiniMax reference analysis, prompt writing, and repair requests have no application output-token cap. Optional supporting video planning has a small bounded response budget. Engine context capacity and provider-side limits still apply.

This page writes **prompt text only**. It does not upload/analyze media, render videos, or call MiniMax's video-generation API. It requires a configured language-model prompt engine; the generic mock backend is for plumbing tests and does not perform H3 semantic rewriting.

</details>

## Installation

**Setup at a glance:** install dependencies → download llama.cpp → download a model + projector → configure → launch.

The walkthrough below uses **Windows PowerShell**. Download the app, llama.cpp, and the model separately; model weights are not included in this repository.

### 1. Install prerequisites

| Requirement | Download / notes |
| --- | --- |
| Python | [Python downloads](https://www.python.org/downloads/) — Python **3.10+**, with **3.12 recommended**. Enable **Add Python to PATH** on Windows. |
| Node.js + npm | [Node.js downloads](https://nodejs.org/en/download) — use a current LTS release, **22.12+**. Node 20.19+ is also supported by this Vite version. |
| Git | [Git downloads](https://git-scm.com/downloads) — optional if you download the repository ZIP instead. |
| llama.cpp | A current build containing **`llama-server`**, with support for your chosen vision model. See step 3. |

> [!IMPORTANT]
> **Plan for model memory.** The example model files total about **6.6 GB on disk**; runtime RAM/VRAM use is higher and depends on quantization, context size, and backend. A supported GPU is recommended. There is no benchmarked minimum-VRAM requirement published for this project.

### 2. Download Goated Prompter and install dependencies

```powershell
git clone https://github.com/Jolanoff/goated-prompter.git
cd goated-prompter

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
npm --prefix frontend ci
npm --prefix frontend run build
```

Alternatively, use **Code → Download ZIP** on [GitHub](https://github.com/Jolanoff/goated-prompter), extract it, open a terminal in the extracted folder, and run the commands starting with `python -m venv .venv`.

The commands use the virtual environment's Python directly, so PowerShell activation is not required. Node.js builds the website; it is not needed to serve an already-built copy.

### 3. Download llama.cpp

1. Open the [official llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases). Choose a current binary release; if a version page links to a nightly build for its assets, follow that link.
2. Download a build matching your OS and hardware: for example, a Windows CUDA build for a compatible NVIDIA GPU, a supported Vulkan build, or a CPU build. Follow the release's driver/runtime requirements.
3. Extract the **entire archive**, including its DLLs/shared libraries. If that release provides a separate required runtime archive, extract it as instructed by the release.
4. Locate `llama-server.exe`. For this guide, assume it is at:

   ```text
   C:\Tools\llama.cpp\llama-server.exe
   ```

Check that it starts:

```powershell
& "C:\Tools\llama.cpp\llama-server.exe" --version
```

You do **not** need to start a separate llama.cpp server for this setup. Goated Prompter launches and manages its own server when you generate. Installing the `llama-cpp-python` package is not a substitute for this executable.

### 4. Download a vision model and its matching projector

A concrete starting option is **Qwen3.5-9B, Q4_K_M**, from [Unsloth's Qwen3.5-9B GGUF repository](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/tree/main).

Download these **two files from that same repository**:

| File | Purpose |
| --- | --- |
| [Qwen3.5-9B-Q4_K_M.gguf](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/blob/main/Qwen3.5-9B-Q4_K_M.gguf) | Main language-model weights, approximately 5.68 GB. |
| [mmproj-BF16.gguf](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/blob/main/mmproj-BF16.gguf) | Matching vision projector, approximately 922 MB. This lets the model process images. |

Use the download button on each file page; you do not need to download every quantization. Keep the model and its matching projector in the **same folder**, and keep `mmproj` in the projector filename. The local engine selector currently requires a complete pair, even if you plan to start with text-only prompts.

Example model folder:

```text
D:\AI\Models\
└── Qwen3.5-9B\
    ├── Qwen3.5-9B-Q4_K_M.gguf
    └── mmproj-BF16.gguf
```

For additional models, give each model/projector pair its own subfolder. Use a model that your llama.cpp build actually supports for vision. The app detects filenames and pairs files within a folder; it cannot prove that weights and projectors from different downloads are compatible.

### 5. Configure and launch

Copy **`config/config.example.json`** to **`config/config.json`**, then set `local_llama_cpp.llama_server` to your actual executable path. Your local config is ignored by Git. Use forward slashes or escaped backslashes in JSON:

```json
"llama_server": "C:/Tools/llama.cpp/llama-server.exe"
```

Leave `"backend": "local_llama_cpp"` selected. If `config.json` is absent, copy `config/config.example.json` to `config/config.json` first. The example uses `llama-server` on PATH; an absolute path is usually easier on Windows. You do not need to hand-edit `model_path` or `mmproj_path` for an engine selected through the website.

The shipped local defaults use `context_size: 32768` and `max_tokens: 4096`. Dataset generation uses bounded output budgets based on the selected prompt length. An unfinished bounded stream is stopped once it exceeds 7,000 generated characters, then that individual prompt can retry up to three times. A 32K context consumes more RAM/VRAM than 8K; lower `context_size` if your hardware cannot load it. Restart the app (and unload any retained model) after changing runtime settings so llama.cpp starts with the new context.

Start the app from the project folder:

```powershell
.\.venv\Scripts\python.exe local_app.py
```

**Open [http://127.0.0.1:8190](http://127.0.0.1:8190)** and keep the terminal running.

1. Open **Settings** in the sidebar.
2. Set **Models directory** to `D:\AI\Models` for the layout above.
3. Click **Save settings**, then **Refresh models** if needed. The saved directory is scanned directly and recursively; an `LLM` subfolder is not required.
4. Return to **Prompt Builder** and choose the discovered **Prompt engine**.
5. Enter an idea, start with **Medium** prompt length, and click **Generate prompt**.

The first generation loads the model and can take longer. **Keep model loaded** retains it between generations; otherwise the app releases its owned server after the operation. **Unload model** is available in Settings.

On later launches, you only need `.\.venv\Scripts\python.exe local_app.py` and the browser. After updating frontend source, run `npm --prefix frontend ci` and `npm --prefix frontend run build` again.

<details>
<summary><strong>Linux / macOS command equivalents</strong></summary>

Use a llama.cpp build appropriate for your OS/GPU, and set `llama_server` to its executable path (for example `/opt/llama.cpp/build/bin/llama-server`) or to `llama-server` if it is on PATH.

```sh
git clone https://github.com/Jolanoff/goated-prompter.git
cd goated-prompter
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-local.txt
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/python local_app.py
```

Use your own absolute model directory in Settings. The browser workflow is the same; the release verification described below was performed on Windows.

</details>

## Using the controls

| Control | What it does |
| --- | --- |
| **Prompt task** | Chooses the type of work and selects its matching instruction preset. You can then choose a different preset. |
| **Instruction preset** | Adds reusable specialist instructions. Changing it does not change the task. |
| **Target model** | Shapes the prompt for the image/video generator you will use afterward. |
| **Planning** | Auto (default) stages structurally complex requests. Direct preserves the original workflow. Always requests one supporting planning pass. |
| **Creativity** | Controls how much new visual detail the writer may introduce. |
| **Prompt length** | Controls descriptive density. Maximum Detail requests a larger output budget, not a guaranteed word count. |
| **Prompt engine** | The language/vision model that actually writes the prompt. |
| **Keep from reference images** | Selects the source for each attribute you want to preserve. |
| **Workflow rules / notes** | Adds constraints for the current request. |

### Optional scene planning

Builder and MiniMax have independent **Auto / Direct / Always** selectors. Direct adds no planning calls or contracts. Simple Auto requests (an apple on a table, a car driving down a street) normally follow Direct. Complex contact, unusual poses, interacting subjects and video sequences can receive **one** compact semantic/staging pass—not a new idea or batch workflow.

Builder plans **after selected reference evidence** and before the unchanged final compiler's target, Director, Creativity and Length controls. MiniMax plans **after its existing symbolic-reference analysis** and before its H3 writer, normalization and repair. Supplied shot order/timing and exact dialogue stay authoritative. Without supplied shots, planning describes continuous progression, not additional cuts.

High-confidence standalone exclusions are compiled internally and applied silently; quoted text, names and ambiguous rules remain intact. Auto logs planning failures and uses the original direct workflow; Always reports a planning failure rather than pretending it succeeded. A small status marks generations that used planning. Internal plans have no separate saved workflow or default geometry UI; the existing live request inspector can show planning activity. Model inference can still misinterpret mechanics or unseen references—planning is supporting guidance, not a semantic guarantee.

### Reference images

Each attribute—subject, face/identity, outfit, pose, scene, composition, camera, lighting, colors, materials, and mood/style—has its own source:

- **Off:** no reference evidence or preservation lock for that attribute.
- **Image 1–4:** keep that attribute from the selected image.
- **Blend:** use all uploaded images for that attribute; requires at least two images.

Only selected source images are analyzed. Their evidence is combined by attribute before the final prompt is written. A selected source lock takes priority over conflicting request wording; switch the attribute **Off** when you want to change it freely.

Slots keep their numbers when an image is removed. Removing a required image resets unavailable selections to **Off**. Images and filenames are not saved, so after reloading the page you must re-upload images and reselect their attributes.

<details>
<summary><strong>Output, saving, and cancellation behavior</strong></summary>

- **Text-only preview** ignores all reference images and preservation selections.
- **End generation** first interrupts the active HTTP request safely. The managed model process is only stopped as a fallback when no cancellable transport is registered. Closing an external request does not guarantee the remote provider stops its computation immediately.
- One generation runs at a time. Settings and preset editing are locked while a job is active.
- **Save Prompt** adds named output text to the saved-prompt library. Instruction presets are a separate library.

The app writes prompts; the quality and faithfulness of the generated description depend on your chosen model and inputs. It does not generate images or videos itself.

</details>

### Refine & version history

Open **Refine** from the sidebar or **Refine & history** under Builder output. Successful website Builder generations are automatically recorded in history. To work on an edited Builder output or another prompt, expand **Start from another prompt**, import the Builder text or paste a prompt, and choose its target model.

1. Enter the change you want, or use a quick action such as **Wider shot**, **Shorten**, or **Remove filler**.
2. Select **Keep these details** locks. These refer to facts in the source prompt; locked attributes take priority over conflicting edits. Unrelated details are preserved by the refinement instructions.
3. Click **Refine prompt**. The original and new version are saved separately, including the requested changes and locks.
4. Expand **What changed** for added/removed text. Use **Undo**, **Redo**, or select any version in history. Refining an older version creates a branch and keeps the previous branch available.
5. **Edit text → Save as new version** records a manual revision. **Save prompt** saves the current version directly to Saved Prompts with its target. **Use in Builder** transfers it back to Builder for further work.

Undo follows the current version's parent; each imported starting prompt or Builder generation begins a new history chain. History selection can restore any chain. The text diff uses bounded work and falls back to highlighting a larger changed region for very large prompts.

<details>
<summary><strong>History storage, autosave, and advanced instructions</strong></summary>

Completed versions and history selection/redo live in **`data/workspace.json`**. Writes are atomic and revision-checked so a stale browser tab cannot overwrite newer workspace edits. The storage limit is 1,000 versions and 16 MiB for the workspace file; copy or back up useful results before clearing history. If saving a generated result fails, its recovered text is shown for copying in the current session.

#### Saved creative settings and advanced instructions

Refine, MiniMax H3, and Dataset settings autosave separately to **`data/workflow_settings.json`**. Refine retains requested changes, locks, starting text/target and manual-edit drafts; MiniMax and Dataset retain their workflow-specific inputs and current results. Wait for the respective **Saved** indicator before closing or reloading. Failed writes keep the local draft and expose retry/reload actions; revision checks prevent a stale browser tab from replacing newer settings.

Dataset generated progress is different: the backend atomically writes completed idea/scene chunks, prompts, repairs and final quality results to **`data/dataset_checkpoints.json`** before displaying them. Browser autosave is needed for your edits, not for completed generation work. Each job records its workflow revision and exact input signature; stale results remain historical and never replace newer settings or manual scenes. After a backend restart, the last durable chunk is recovered as interrupted work, not silently resumed inference. Generate from the recovered plan to continue.

Expand **Refine advanced settings** to edit its built-in behavior. **Save instructions** activates edits for subsequent generations; **Discard instruction edits** restores the saved editor text; **Use built-in instructions** resets the workflow to its shipped default. Unsaved instruction-editor changes require an explicit save before reload, unlike the ordinary autosaved controls.

Custom workflow instructions replace the corresponding built-in behavior. Target formatting and detail locks are still applied separately, including JSON validation for Ideogram4. Instruction changes are blocked during generation, and each job uses a snapshot of the saved instructions. Builder's instruction-preset library stays independent of these workflow-specific editors.

</details>

### Dataset prompt batches

Build a batch around one concept, keep shared details consistent, and vary the scenes. Review the planned ideas before writing final prompts, or generate everything in one click.

1. Describe the **Dataset idea** and choose a subject type, amount (**1–25**), and variety.
2. Add consistency rules, optional guided scene ideas, and training triggers if needed.
3. Choose the visual treatment, Director preset, target model, and prompt length.
4. Click **Generate prompts**, or **Plan scenes first** to inspect and edit the ideas and scenes.
5. Review quality warnings, edit your results, and export **TXT**, **JSONL**, or **Scenes JSON**.

<details>
<summary><strong>Dataset controls, scene planning, and validation details</strong></summary>

Open **Dataset** and start with **Dataset idea**: describe the subject and what should happen, for example “a woman doing funny stuff.” Choose Subject type, Amount and Variety, then final visual treatment, target and prompt length. Character, multiple-character, animal, object/product, visual-style, location/environment, brand/logo, typography/text, concept and custom types receive appropriate planning guidance. Training trigger controls are separate and collapsible; opaque trigger tokens are not sent to Scene Planner as visual descriptions.

**Require trigger at the beginning** strongly requests beginning placement when enabled; while off, the model is encouraged to write a natural visual introduction first. **Keep trigger text connected** requests the complete input as one phrase; turn it off to encourage comma-, line-, or `and`-separated terms in different meaningful positions, such as `woman, cake` or `1 man and 1 girl`. Placement and grouping remain warning-only preferences. **Allow the model to expand the trigger** is off by default: every trigger term must appear exactly as typed, including capitalization and word order. Missing exact wording retries only that final prompt, preserving its idea and scene. With expansion enabled, articles, capitalization and inserted descriptors may vary: `a banana` can become `A muscular anthropomorphic banana`, but both banana and apple must still be mentioned for `a banana, an apple`. Subject/attribute words are matched as whole words in order; unknown semantic paraphrases need manual review, and custom identifier tokens remain protected. When expansion is off, the model may still describe actions, poses, interactions, scene-relevant clothing or use, composition, and lighting, but it must not invent intrinsic identity, appearance, design, material, style, or location properties unless the concept, rules, guided input, or trigger explicitly supplies them.

The **dataset concept** is the recurring activity, relationship, environment, or theme shared by the batch—for example, “their adventures together.” **Consistency and variation rules** state both fixed requirements (“the man is taller and has a beard”) and deliberate changes (“use a different adventure and outfit in every prompt”). Explicit rules are allowed even when trigger expansion is disabled.

Choose 1–25 prompts, a realistic or non-realistic visual treatment, variety level, Director preset, target model and prompt length. **Let Scene Planner invent scenes** develops distinct visible events inside your concept and rules. **Provide my own scene ideas** uses one line per idea. Scene Planner improves each guided idea without replacing its central action or named objects; when lines cycle, only permitted context and presentation vary.

Scene Planner follows your concept, consistency rules, and guided inputs, choosing compatible action, expression, framing, setting, and lighting rather than receiving automatic facet assignments.

Older coverage settings are ignored when loading saved drafts. Existing scenes and prompts remain readable; scene plans from before this change need replanning once before reuse.

Generation follows **user concept → guided selection (if supplied) → Scene Planner → existing final writer → target-specific prompt**. Fast mode combines idea and scene in chunks of four; Quality mode plans all ideas, then composes scenes in chunks of four. A ten-item batch composes 1–4 / 5–8 / 9–10 in either mode. Later Fast chunks receive the original concept, constraints, current assignments and accepted idea summaries; failed chunk retries never regenerate accepted chunks. Output contains `{index, idea, scene, geometry}`. Ideas remain short semantic interpretations (maximum 30 words / 240 characters); scenes remain concise spatial realizations (maximum 120 words / 1,000 characters). Newlines and whitespace normalize without repair, as do obvious enum spellings and framing aliases. Character geometry requires only framing, camera azimuth, body orientation, head direction, gaze direction and face visibility. All helper metadata is optional, including details for custom poses/expressions. Scene prose remains authoritative for unusual staging. Shoes/feet-central actions deterministically widen incompatible incidental crops and record a framing diagnostic; the idea always wins. No coverage planner is restored. Instructions live in `goated_prompter/prompting/scene_planner.py`; planning validation and versioned reuse signatures live in `goated_prompter/scene_planner.py`. Target syntax, Director instructions and trigger tokens stay out of planning.

**Type-aware staging:** Both Fast and Quality use `goated_prompter/dataset_staging/`. `vocabulary.py` holds canonical values; `schema.py` defines fields once; `profiles.py` selects required/recommended/applicable fields, per-profile enum restrictions and registered rule groups for all ten Dataset types. `prompt_schema.py` generates the model's schema from those same field and value restrictions. Camera azimuth, elevation and distance are independent axes; framing describes which content is included, while distance describes physical camera proximity. Character uses explicit common + human fields without duplicate generic orientation. Non-human profiles use `detail_close_up`, `full_subject`, `full_subject_with_environment`, `wide` and `extreme_wide`, not human crop labels. Safe whole-subject legacy labels migrate on load; ambiguous crops receive local warnings. Multiple characters require scene-level framing, azimuth, composition, primary count and action visibility, not a shared head/gaze/face state. Animal, Product, Environment, Brand, Text, Style, Concept and Custom do not run Character anatomy rules or require human fields. Custom stays generic without automatic leg/pelvis/back fields; unusual posture/viewpoint goes in applicable `pose_detail`, `view_detail` and focus fields. Requested specialized pose/head vocabulary is retained in the Character profile.

Lexical normalization precedes field-specific aliases and enum validation: `framing=medium` becomes `waist_up` without another model call for Character. Known emotional gaze mistakes move to `expression` only if no existing fact conflicts; supported head/eye-position states stay in `head_direction`. A required missing gaze is never invented from head orientation: an explicit, unambiguous gaze in scene prose may supply it, otherwise only that scene receives field-specific repair while its idea and valid siblings remain unchanged.

Structured runtime output validation dispatches from target capabilities. MiniMax H3 video output requires complete nonempty named sections in order and receives a bounded format-only retry if malformed. The dedicated MiniMax workflow shares that section validation while retaining its reference/timeline checks; non-video Builder/Dataset tasks remain image tasks.

`normalize.py` handles spelling/aliases without physics. `migration.py` loads older `camera_view`, `camera_height`, `gaze`, `pose` and mixed orientation facts conservatively: safe camera facts move to the appropriate axis, unusual facts become details, and no missing side/elevation is invented. Ambiguous rows receive `geometry_warning` for local repair while their ideas, scenes, prompts and valid siblings remain loadable. Safe field renames do not bump the scene-plan signature or force all current saved plans to replan. Saved/manual scenes with no geometry remain authoritative and are not rewritten just to fill metadata; explicit prose contradictions and incomplete supplied staging still need repair. New model output always enforces its selected profile in both modes. `engine.py` runs modular `rules/` and returns structured issues with fields, severity and repair guidance; `geometry_errors()` retains string-message compatibility. Prose contradiction checks live in `rules/prose.py`, with no dependency on Dataset quality. `dataset_geometry.py` is only a temporary import facade. Add a future field in the registry, assign it to profiles, and add an optional rule/test—do not duplicate schema lists in the planner.

**Generate prompts** remains one-click. Optionally click **Plan scenes first**, inspect/edit the separate Idea and Scene fields, then **Generate prompts from these scenes**. Keep manual edits to both consistent; editing an idea does not automatically recompose its scene. Planning alone needs no training trigger. The `scene_plan` stores `{index, input, idea, scene}` with its semantic signature, separate from results. Target, length, Director and trigger-format changes reuse both; concept, inputs, amount, type, variety, constraints or visual style changes invalidate them. New final and partial results preserve `{index, input, idea, scene, prompt}`. Editing a plan affects the next generation, never the provenance recorded with an existing prompt. JSONL includes both originating idea and scene; **Scenes JSON** exports the plan. TXT and Copy all remain final-prompt-only. Completed chunks are backend-persisted; wait for **Dataset settings: Saved** for manual edits. Legacy scene-only prose and manually edited scenes can remain usable without geometry or invented idea provenance. Original-input fallbacks remain loadable even when longer than normal model output.

**Guided inputs** accept full scene ideas or partial anchors (place, pose, outfit, prop or action). A partial line such as “park” is completed creatively within the shared concept while keeping that setting; a supplied action such as sitting on a table stays authoritative. Details in a line apply only to that line's assignments, not the whole batch. Shared identity does not automatically lock clothing. Lines cycle in order when the requested amount exceeds the line count: six lines for ten images map to lines 1–6, then 1–4 again. Different compatible completions are encouraged for repeated partial anchors, but exact scene repetition is valid for the same nonempty guided input. Random-mode duplicates and duplicates across different guided inputs still require repair. If an older run fell back to raw lines, use **Replan scenes** after restarting to replace that fallback; existing plans/edits are not automatically overwritten by this fix.

The final Dataset writer uses existing Builder assembly (Enhance mode, selected Director, target adapter and target-resolved length guidance) with strict creativity. It receives **PLANNED IDEA** for semantic purpose and **PLANNED SCENE** for physical staging. Local enrichment must preserve action, props and geometry; Director technique is subordinate to the plan and rules. Dataset detail is scene-dense, not filler-dense. Earlier full prompts are not supplied. Real contradictions receive up to three local scene repairs, never replacement ideas. If repair fails, that row keeps its idea and becomes failed/retryable while valid siblings and later chunks remain available. Use **Repair scene** to retry it. Idea replacement is reserved for Idea Planner semantic-duplicate handling or explicit user-requested idea regeneration. Formatting/schema corrections remain bounded. Tests validate orchestration, not actual LLM coherence or creativity.

**Visible content only:** Dataset planning and writing describe what the intended image contains, not a list of what to exclude. Single-subject and exclusion constraints shape composition silently. Use positive visible states such as a sparsely furnished room, naturally resting hands, an empty abandoned street or an unoccupied chair. Internal quality slogans, negative-conditioning lists and exclusion commands do not belong in positive prose. The compact shared LLM rule and strict phrase checks live in `goated_prompter/dataset_visible_content.py`; forbidden examples stay in code/tests, not the visible-content system rule. New planner output with detected leakage still receives the existing one repair. Final generation (including recovered runaway prefixes) follows **normalize target output → general text cleanup / trigger check → conservative positive-content cleanup → strict positive-content validation → accept or bounded retry**. `sanitize_positive_prompt()` removes complete, clearly standalone exclusion/meta clauses, never global word replacements or useful prose mixed with restrictions. A removable clause costs no additional generation call. Literal quoted content, protected triggers and meaningful visible absence remain intact. Ideogram cleanup touches only positive description strings, preserving rendered `elements[].text`, other JSON fields and required nonempty descriptions. Unsafe/remaining leakage uses **OUTPUT CONTENT CORRECTION**, without echoing the offending phrase; malformed target structures use **FORMAT CORRECTION**. Repeated invalid output fails validation rather than silently saving it. Existing/manual results can show leakage warnings in quality analysis and Deep Review. Checks are conservative heuristics, not a universal ban on words like “no,” and cannot detect every paraphrase. Raw-input fallback plans retain original wording as recovery data; the writer must still interpret exclusions silently and pass positive-output checks. Normal Builder and other workflows are unchanged, and no negative-prompt field has been added or concatenated into positive output.

Generation runs sequentially in one model session. Completed items appear while the batch runs and are retained if a later item stops or fails. Invalid target format, missing protected trigger wording, or runaway output gets up to three writer retries; exhausted retries mark only that prompt failed without replacing its idea or scene. Loop retries progressively shorten density and output allowance without losing the target envelope or restoring a larger allowance during repair. A sentence-complete prefix may be recovered if it passes validation, including the selected trigger-expansion policy. With expansion on, unrecognized subject wording remains a review warning, not an automatic rewrite. Placement and grouping misses remain warnings in either mode. Results are editable and exportable as TXT or JSONL. For Ideogram4, trigger checks apply inside `high_level_description` so the outer JSON remains valid. Anima's supported standalone positive quality/score tags are exempt from the generic quality-slogan sanitizer; negative lists remain disallowed in positive prose.

After generation, the local **Dataset quality report** checks triggers, format, leakage, prompt duplicates, guided assignments, idea similarity and scene repetition separately. Idea hints respect guided/Focused repetition and explicit facial-expression scope. Narrow geometry warnings catch explicit rear/frontal-face conflicts, tight face/upper-body crops claiming visible shoes, and directly conflicting camera positions; they skip negated requirements and reflected/multi-panel cases rather than pretending to simulate anatomy. These English-text heuristics miss paraphrases and can flag legitimate similarities. Optional **Deep consistency review** compares saved IDEA + SCENE + FINAL PROMPT against concept and constraints; lost semantic purpose is included under `scene_drift`. It also checks camera/body/head/gaze/pose/crop/prop contradictions, differentiating writer-introduced drift from existing usability problems, without penalizing interpretable unusual/stylized poses. It uses groups of four prompts and 2,048 output tokens per group; it does not generate fixes or new scenes. Legacy missing provenance cannot be reliably audited for originating idea/scene drift. Reports autosave; prompt edits recompute deterministic checks.

The real-model evaluation fixture and scoring checklist are in [`tests/fixtures/scene_planner_eval.md`](tests/fixtures/scene_planner_eval.md). Automated tests validate the pipeline with mocks, not LLM creativity or semantic fidelity. `/api/workspace/dataset/scenes` starts a planning-only job.

</details>

## Project and data layout

The website runs on loopback only. With the local backend, inference stays on your machine and UI assets/fonts are bundled locally. A remote OpenAI-compatible endpoint receives generation inputs, including selected images.

> [!TIP]
> Back up **`data/` and your configuration** to preserve prompts, history, presets, and settings. Keep downloaded models and llama.cpp outside the source tree.

<details>
<summary><strong>Directory structure and local storage</strong></summary>

```text
goated-prompter/
├── local_app.py                 # Website launcher and local HTTP API
├── requirements-local.txt      # Standalone Python dependencies
├── config/
│   ├── config.example.json     # Portable configuration template
│   └── config.json             # Backend / llama-server configuration
├── goated_prompter/
│   ├── planning/               # Shared constraints and optional single-pass scene/video staging
│   ├── prompting/              # Prompt content split by concern
│   │   ├── modes.py            # Prompt task modes
│   │   ├── directors.py        # Built-in Directors
│   │   ├── target_models.py    # Target-model adapters
│   │   ├── base.py             # Base and priority contracts
│   │   ├── output.py           # Final output contract
│   │   ├── creativity.py       # Creativity controls
│   │   ├── details.py          # Detail, preservation and reference controls
│   │   ├── refine.py           # Refine prompt construction
│   │   ├── minimax.py          # MiniMax prompt schemas and validation
│   │   ├── dataset.py          # Dataset prompt construction
│   │   └── scene_planner.py    # Dataset-only scene ideation instructions
│   ├── presets.py              # Instruction-preset storage and library management
│   ├── core.py                 # Prompt assembly and generation orchestration
│   ├── scene_planner.py        # Batch scene planning, validation and fallback
│   ├── refinement.py           # Refine inference runtime
│   ├── workflow_settings.py    # Per-workflow drafts and instruction overrides
│   ├── workspace_api.py        # Creative-workspace endpoints and shared-job integration
│   ├── workspace_store.py      # Atomic versions and branching undo/redo
│   ├── reference_map.py        # Attribute-to-image source mapping
│   ├── evidence.py             # Image analysis and resolved scene evidence
│   ├── input_schema.py         # Website input options and bootstrap defaults
│   └── backends/               # llama.cpp and OpenAI-compatible clients
├── frontend/
│   ├── src/                    # React UI, Tailwind utilities and presentation labels
│   │   └── workflows/          # Refine, MiniMax, Dataset and workspace state
│   └── dist/                   # Generated by npm run build; not committed
├── data/                       # Created as you save; not committed
│   ├── settings.json           # Settings and autosaved builder draft
│   ├── prompts.json            # Saved prompt collection
│   ├── workspace.json          # Versions and undo/redo history
│   ├── workflow_settings.json  # Workflow drafts and custom instructions
│   └── directors/              # Custom instruction presets
│       └── .overrides/         # Edits to built-in instruction presets
└── tests/                      # Python, frontend, and browser workflow tests
```

Keep downloaded models and llama.cpp outside this source tree, as in the installation examples. Back up **`data/` and your configuration** to preserve your setup. Wait for the builder's **Saved** status before closing; stop the server before manually editing its JSON stores.

Existing SQLite settings and browser-saved prompt collections have migration paths. A browser collection is imported when you revisit its original browser/address; the original copy is retained if importing fails.

</details>

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `python` or `npm` is not recognized | Install the prerequisites with PATH enabled, then open a new terminal. On Windows, `py -3.12 -m venv .venv` can be used if the Python launcher is installed. |
| Website says to build `frontend/dist` | Run `npm --prefix frontend ci`, then `npm --prefix frontend run build`. |
| No prompt engines appear | Save an existing **Models directory**; put a main `.gguf` and matching `mmproj*.gguf` in each model folder; refresh models. |
| `llama_server executable was not found` | Set the full executable path in `config/config.json`, test it with `--version`, then restart Python. |
| llama.cpp exits during startup | Run its `--version` check; verify DLLs/drivers, a current build, compatible GGUF/projector files, and available memory. |
| Loading takes too long | The first request loads the model. Check `startup_timeout` in the config and your hardware. CPU inference can be much slower. |
| Maximum Detail reports insufficient context or truncation | Try Medium/Detailed first, reduce long instructions, or increase the engine context. Application output-token caps are disabled, but model context capacity and provider-side limits still apply. |
| Editing code has no visible effect | Python changes require a server restart. Port **8190** serves built frontend files; rebuild or use Vite on **5173** for live frontend editing. |
| Reference selections disappeared after reload | Images are not persisted; re-upload them and set their sources again. |

## Other backends

For an existing OpenAI-compatible server, replace the configuration with your endpoint/model details:

```json
{
  "backend": "openai_compatible",
  "openai_compatible": {
    "base_url": "http://127.0.0.1:1234/v1",
    "model": "your-model-name",
    "api_key_env": "GOATED_PROMPTER_API_KEY",
    "temperature": 0.5,
    "timeout": 180
  }
}
```

Set `GOATED_PROMPTER_API_KEY` in the environment if authentication is required. The endpoint and model must support vision for reference images. Local model discovery is not required for this backend. `{"backend": "mock"}` is available for text-only UI/assembly checks without an LLM; its output is intentionally just a marked mock result.

`GOATED_PROMPTER_CONFIG` selects an alternative config file. Configuration otherwise uses `config/config.json`. `GOATED_PROMPTER_USER_DIR` overrides instruction-preset storage, which defaults to `data/directors/`. `GOATED_PROMPTER_DEBUG_PROMPTS=1` enables full prompt diagnostics in the server console.

## Development and verification

Want to help? Read the [contribution guide](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md). Use the [issue forms](https://github.com/Jolanoff/goated-prompter/issues/new/choose) for bugs and feature requests; report vulnerabilities according to the [security policy](SECURITY.md).

### Checkpoint privacy and recovery

Dataset generated checkpoints are durable local content in **`data/dataset_checkpoints.json`**, separate from editable settings. Up to 20 recent job records are retained, subject to the local 16 MiB store limit. Other workflows' runtime checkpoints, live request/response logs and interrupted partial-text diagnostics remain RAM-only. Dataset exports/Clear release completed RAM jobs and hide their diagnostic recovery endpoints; they do not erase durable scenes/prompts. Active jobs are never deleted by cleanup. Shutdown uses bounded cancellation, marks unfinished work interrupted and releases RAM diagnostics. Backend restart recovers completed Dataset chunks, not active sockets or partial prompts.

This cleanup does **not** remove your existing autosaved drafts (`settings.json` / `workflow_settings.json`), named saved prompts, version history, downloaded exports or clipboard content. Those still contain private content locally. Keep `GOATED_PROMPTER_DEBUG_PROMPTS` disabled to avoid content in console logs. Remote inference providers have their own retention policies; releasing Python references is not guaranteed secure memory erasure.

Model streams require an explicit completion reason (`stop`); EOF or `[DONE]` without a reason is not assumed successful. Diagnostics distinguish interrupted, token-limit, cancelled, provider-error and malformed-stream outcomes and retain partial text without presenting it as a finished prompt. Local HTTP requests can be interrupted during headers and streaming, and their configured timeout is also a total deadline. DNS/connect operations remain subject to operating-system/network timeouts. Structured-output budgets are checked against the configured context estimate before sending; uncapped Builder/video contracts remain unchanged.

<details>
<summary><strong>Live development and project conventions</strong></summary>

For live frontend edits, run the backend in one terminal and Vite in another, from the project root:

```powershell
.\.venv\Scripts\python.exe local_app.py
```

```powershell
npm --prefix frontend run dev
```

Open **http://127.0.0.1:5173**. Vite proxies `/api` to the backend on port 8190.

Static prompt content is organized by concern in **`goated_prompter/prompting/`**. Restart Python after editing it. Keep saved option keys stable. For new tasks, add both the option and its adapter in the relevant file. Website-only display names/order live in `frontend/src/App.jsx` and `frontend/src/presetPresentation.js`.

</details>

<details>
<summary><strong>Build checks, unit tests, and browser tests</strong></summary>

Run the checks from the project root:

```powershell
npm --prefix frontend run build
npm --prefix frontend run lint
.\.venv\Scripts\python.exe -m unittest discover -s tests
npm --prefix frontend test
```

Building first also enables `tests/test_built_site.py`, which checks that Python serves the compiled assets and completes a mock generation with fresh temporary storage.

Browser tests use a delayed mock backend and temporary settings, prompts, and preset storage. To make `python` resolve to your virtual environment for Playwright, activate it in the test terminal or put `.venv/Scripts` on that terminal's PATH. Install Chromium once using `npm --prefix frontend exec -- playwright install chromium`, then run:

```powershell
npm --prefix frontend run test:e2e -- --config e2e/isolated.config.js
```

On Windows with Edge installed, use `$env:PLAYWRIGHT_CHANNEL = "msedge"` before the test command instead of downloading Chromium. The isolated configuration uses ports **8191/5191** and refuses to reuse an existing server.

Automated checks cover prompt assembly, reference mapping, API/storage behavior, and browser workflows. Mock tests do not measure real-model output quality, GPU compatibility, or performance. Report issues with your OS, Python/Node versions, llama.cpp build/backend, exact model/projector filenames, and the relevant error at [GitHub Issues](https://github.com/Jolanoff/goated-prompter/issues).

GitHub Actions runs lint, unit/API tests and builds on Python 3.10/3.13, plus Chromium workflow tests. Reliability regressions include actual HTTP socket interruption and heartbeat deadlines, unexpected stream EOF, manual-scene regeneration, ambiguous gaze ownership and checkpoint cleanup. Real-model quality still requires evaluation on your configured engine; no model downloads or external inference calls occur in these checks.

The reusable quality corpus, frozen real responses, annotation rubric and JSON/Markdown reporting live in **[`tests/eval/`](tests/eval/README.md)**. It covers Builder, Dataset writer parity, MiniMax temporal/reference behavior, specialized domains, constraints and five-run novelty probes. Fidelity, useful detail density and semantic repetition require explicit review; missing annotations never count as success. CI publishes frozen replay reports without inference. Live evaluation requires an explicit existing engine and `--allow-live`; notify the GPU owner first.

</details>

Goated Prompter is a standalone browser-based application, not a node extension or bundled desktop installer. Installing only the Python package does not build or bundle the website.

---

## License and credits

[Goated Prompter Source-Available License 1.0](LICENSE) — copyright (c) 2026 Jolanoff.

- **Allowed:** free use and redistribution, modifications, internal business/client work, and monetizing prompts or creative content made using the app.
- **Not allowed:** selling or renting the app or its forks, paid software bundles containing it, or charging for hosted access, API access, subscriptions, or app features.
- Keep the license and copyright notice with redistributed copies and identify modifications. See `LICENSE` for the full terms.

This is a custom source-available license, **not MIT or an OSI-approved open-source license**. Previously released MIT versions retain their MIT permissions; these restrictions apply to versions distributed under the new license.

Built with React, Tailwind CSS, Vite, aiohttp, Pillow, and llama.cpp. Downloaded models and third-party dependencies retain their own licenses; model weights are not distributed with this project.

<div align="center">

[Back to top](#top)

</div>
