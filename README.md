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

## See it in action

<!--
Demo: drag a short MP4 (15–25 s: trigger and concept → Understanding → ideas → final prompts)
into this file in the GitHub editor and GitHub inserts a playable video link here.
A GIF also works: save it as docs/media/dataset-demo.gif and use
<p align="center"><img src="docs/media/dataset-demo.gif" alt="Dataset tab turning one concept into a batch of prompts" width="900"></p>
-->

<!--
Screenshots: save PNGs in docs/media/ with these names, then remove this comment's markers.

| Prompt Builder | Dataset |
| --- | --- |
| <img src="docs/media/builder.png" alt="Prompt Builder" width="440"> | <img src="docs/media/dataset.png" alt="Dataset" width="440"> |
| **Refine** | **Prompt Library** |
| <img src="docs/media/refine.png" alt="Refine" width="440"> | <img src="docs/media/prompt-library.png" alt="Prompt Library" width="440"> |
-->

## Features

| Workflow | What you can do |
| --- | --- |
| **Prompt Builder** | Turn text and up to **four reference images** into target-aware prompts. Mix a face from one image, a pose from another, and lighting from a third. |
| **Refine** | Paste a prompt or send one from Builder, request targeted edits, compare changes and undo a refinement. |
| **MiniMax H3** | Write video prompts for **4–15-second clips**, with symbolic references, automatic role analysis, H3 schemas, and Director presets. |
| **Dataset** | Create **1–25 varied prompts** from one request, for LoRA training sets. You confirm the request first; optional vocabulary packs you pick add creative material, and a seed repeats or varies a batch. TXT/JSON export. |
| **Saved Prompts** | Add your own prompts directly, keep named outputs, and open saved text in Builder. |
| **Prompt Library** | Add, edit and delete target-specific writing examples in a compact list. Stored in the same plain-text files. |

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
- Local prompting knowledge and source links live in [`goated_prompter/features/minimax/knowledge`](goated_prompter/features/minimax/knowledge/SOURCES.md). No documentation fetch is needed during generation.
- Output validation checks H3 section order, exact frame alignment, shot timing, reference IDs, retention markers and dialogue syntax before delivery. Invalid output gets one repair attempt; a failed attempt leaves your previous output intact.
- MiniMax reference analysis, prompt writing, and repair requests have no application output-token cap. There is no separate scene-planning pass. Engine context capacity and provider-side limits still apply.

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

The shipped local defaults use `context_size: 32768` and `max_tokens: 4096`. Dataset generation uses bounded output budgets based on the selected prompt length. An unfinished bounded writer stream is stopped once it exceeds 7,000 generated characters; that individual prompt gets at most one retry. A 32K context consumes more RAM/VRAM than 8K; lower `context_size` if your hardware cannot load it. Restart the app (and unload any retained model) after changing runtime settings so llama.cpp starts with the new context.

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

Dropdown menus follow the app theme in browsers that support customizable native selects (Chrome and Edge 135+). Other browsers keep their native menus and keyboard controls.

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

Builder has an **Auto / Direct / Always** selector. Direct adds no planning calls or contracts. Simple Auto requests (an apple on a table, a car driving down a street) normally follow Direct. Complex contact, unusual poses and interacting subjects can receive **one** compact semantic/staging pass—not a new idea or batch workflow.

Builder plans **after selected reference evidence** and before the unchanged final compiler's target, Director, Creativity and Length controls. MiniMax goes directly from symbolic-reference analysis to its H3 writer, normalization and repair. Supplied shot order/timing and exact dialogue stay authoritative.

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
- In **Saved Prompts**, click **Add prompt** to paste or write your own text, name it and choose its target model. No Builder generation is needed. Failed saves keep the form available for retry.
- **Per-target prompt library**: on first launch the app creates one text file per target model in `data/prompt_library/` (for example `krea-2.txt`). Use **Prompt Library** to select a target and add, edit or delete prompts in a compact list, or paste prompts into the text file separated by a line containing only `---`. Library prompts are templates for how a good prompt is *written*, not for what the image shows: see [Prompt library as a style template](#prompt-library-as-a-style-template). There are no built-in example prompts; an empty library means the writer follows only the target's rules (Qwen Image 2.1 editing keeps one worked edit example). **Remix** (Builder) recasts a saved prompt with your characters.

The app writes prompts; the quality and faithfulness of the generated description depend on your chosen model and inputs. It does not generate images or videos itself.

</details>

### Refine

Open **Refine** from the sidebar and paste into **Prompt**, or click **Refine prompt** under Builder output to fill that same editable box. Choose the prompt's target model. There is no separate import or starting-prompt step.

1. Enter the change you want, or use a quick action such as **Wider shot**, **Shorten**, or **Remove filler**.
2. Select **Keep these details** locks. These refer to facts in the source prompt; locked attributes take priority over conflicting edits. Unrelated details are preserved by the refinement instructions.
3. Click **Refine prompt**. The result replaces the text in **Prompt**. You can refine it again or paste a different prompt into the same box.
4. Expand **What changed** for added/removed text. **Undo** returns to the source of the refinement. The version list, Redo and history-management controls are not shown.
5. **Copy prompt**, **Save prompt** and **Use in Builder** act on the text currently in the box, with its selected target.

The app records the exact source automatically before refining it, so Undo and What changed work for both Builder output and pasted text. The text diff uses bounded work and falls back to highlighting a larger changed region for very large prompts.

<details>
<summary><strong>Undo storage, autosave, and advanced instructions</strong></summary>

Undo still uses the existing versions in **`data/workspace.json`** internally. Writes are atomic and revision-checked so a stale browser tab cannot overwrite newer workspace edits. The existing storage limit is 1,000 versions and 16 MiB for the workspace file. Refine has no history browser or clear-history control. If saving a generated result fails, its recovered text is shown for copying in the current session.

The coding assistant must not inspect private **`data/`** contents. This is not a runtime restriction: the app still reads and writes its stores and sends the content selected for generation, including saved Director instructions, to your configured local LLM. Evaluation corpora live under **`tests/`** and generated evaluation artifacts under **`quality-artifacts/`**, separate from app storage.

#### Saved creative settings and advanced instructions

Refine, MiniMax H3, and Dataset settings autosave separately to **`data/workflow_settings.json`**. Refine retains requested changes, locks and editable prompt/target drafts; MiniMax retains its inputs and current result, and Dataset its settings (Dataset runs are saved separately, see below). Wait for the respective **Saved** indicator before closing or reloading. Failed writes keep the local draft and expose retry/reload actions; revision checks prevent a stale browser tab from replacing newer settings.

Expand **Refine advanced settings** to edit its built-in behavior. **Save instructions** activates edits for subsequent generations; **Discard instruction edits** restores the saved editor text; **Use built-in instructions** resets the workflow to its shipped default. Unsaved instruction-editor changes require an explicit save before reload, unlike the ordinary autosaved controls.

Custom workflow instructions replace the corresponding built-in behavior. Target formatting and detail locks are still applied separately, including JSON validation for Ideogram4. Instruction changes are blocked during generation, and each job uses a snapshot of the saved instructions. Builder's instruction-preset library stays independent of these workflow-specific editors.

</details>

### Dataset prompt batches

Build a batch around one request, keep shared details consistent, and vary the scenes. Every batch begins with Understanding and your approval.

1. On **Configure**, write the **Request**, choose **NSFW** and the **Amount** (**1–25**), and add an optional **Trigger** for LoRA training. **Advanced options** hold consistency rules, the seed and whether the trigger must start each prompt.
2. Choose the Director preset, target model, prompt length, creativity and style. The Director and target model shape the final prompts; the scenes are written without a Director. Directors that need reference images, edit an image or write video are not offered here.
3. Choose the scene source: **Invent scenes**, or **Use my scene ideas** with one idea per line (lines cycle to fill the batch). Your own scene ideas are used as written, without vocabulary.
4. With **Invent scenes**, optionally open the **Vocabulary Library** to select vocabulary packs (search, filter by category, preview, then **Apply**). The selection is saved with your Dataset settings. With an **Actions & Poses** pack selected, every scene is built on one of its entries, and no entry is used by more than two images (more only when the pack has fewer entries than images). No pack is used automatically; select a **Subjects** pack yourself if you want it to guide character looks.
5. Click **Generate** or **Generate scenes only**. Check what the review says stays fixed and what varies, then **Confirm**. Nothing is written before you confirm.
6. The **Scenes** page shows each image's scene as soon as it is written, and **Dataset** shows each final prompt as soon as it is written. Copy them or download TXT or JSON. **Export generation log** saves the current state to a file.

Runs are not saved by the app; copy or download what you want to keep. Editing scenes, regenerating single images and continuing a scenes-only run are not available. **Seed** and **Seed control** work like ComfyUI: the seed drives the engine and the order in which vocabulary and looks are offered, so Fixed repeats a batch as closely as the engine allows, and Increment and Randomize give different scenes.

#### Adult content (Dataset only)

Adult (NSFW) requests are supported in the Dataset tab only, and everyone must be an adult: a request that makes someone a child or teen is refused before generation, and an adult batch can never involve an animal. The repository ships only general vocabulary; keep adult packs in your own `data/vocabulary/` by importing them.

Freaky stuff are ignored. Generating freaky stuff is at your own risk. I'm not responsible of any prompt you generate.

#### Vocabulary packs

Each category is a folder under `vocabulary/` (Subjects, Actions & Poses, Spaces, Objects, Expressions, Clothing, Mood & Tone, Lighting, Camera & Composition, Effects & Atmosphere), and each JSON file in it is one pack, for example
`{"name": "Rooftops", "category": "Spaces", "entries": ["rooftop bar", "water tower"]}`. Click **Import packs** on the **Vocabulary** tab and choose one or more pack files: each is checked and saved in `data/vocabulary/<its category's folder>/`, and importing the same file again replaces it. A pack that cannot be read is listed there with the reason, and every other pack keeps working. The categories are defined in `vocabulary/core/` (`scene_category_registry.json`, `category_definitions.json`, `prompt_instructions.json`); a new category is one entry in each plus its folder.

See the [Dataset architecture](docs/dataset-architecture.md) for how a run is understood, composed and written.

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
│   ├── features/               # Backend code per app tab, mirroring frontend/src/features/
│   │   ├── builder/            # Prompt assembly, reference evidence, generation, /api/generate
│   │   ├── refine/             # Refine service, prompt text and version-history routes
│   │   ├── minimax/            # MiniMax H3 contract, prompt text, knowledge files and routes
│   │   ├── dataset/            # Dataset routes and runner; v2/ holds Understanding, scenes, prompts and runs
│   │   ├── saved_prompts/      # Saved prompt collection store and routes
│   │   ├── presets/            # Instruction preset library routes
│   │   └── settings/           # Settings validation, model discovery and unload routes
│   ├── options/                # Option catalogs: targets, modes, lengths, references, MiniMax, Dataset, locks
│   ├── api/                    # Request plumbing shared by routes, and workflow-settings routes
│   ├── prompting/              # Prompt content shared by several tabs (base, output, targets, modes, directors)
│   ├── planning/               # Shared constraints and optional single-pass scene/video staging
│   ├── backends/               # llama.cpp and OpenAI-compatible clients
│   ├── contracts.py            # Engine request, prompt instruction and generation result
│   ├── workflow_runners.py     # Dispatches each job to its tab's runner
│   ├── workflow_settings.py    # Per-workflow drafts and instruction overrides
│   ├── workspace_store.py      # Atomic versions and branching undo/redo
│   ├── presets.py              # Instruction-preset storage and library management
│   └── reference_map.py        # Attribute-to-image source mapping
├── frontend/
│   ├── src/                    # React UI, Tailwind utilities and presentation labels
│   │   ├── features/           # One folder per workflow: components, hooks, utilities and tests
│   │   └── shared/             # Workflow controls and saved-settings hooks used by several workflows
│   └── dist/                   # Generated by npm run build; not committed
├── data/                       # Created as you save; not committed
│   ├── settings.json           # Settings and autosaved builder draft
│   ├── prompts.json            # Saved prompt collection
│   ├── workspace.json          # Versions and undo/redo history
│   ├── workflow_settings.json  # Workflow drafts and custom instructions
│   ├── vocabulary/             # Your imported vocabulary packs, one folder per category
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

Backend names ignore surrounding whitespace, casing and hyphen/underscore differences. Existing aliases (`openai`, `debug`, `llama_cpp`, `llamacpp`) remain supported; the website API publishes their canonical names (`openai_compatible`, `mock`, `local_llama_cpp`).

`GOATED_PROMPTER_CONFIG` selects an alternative config file. Configuration otherwise uses `config/config.json`. `GOATED_PROMPTER_USER_DIR` overrides instruction-preset storage, which defaults to `data/directors/`. `GOATED_PROMPTER_DEBUG_PROMPTS=1` enables full prompt diagnostics in the server console.

## Development and verification

Want to help? Read the [contribution guide](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md). Use the [issue forms](https://github.com/Jolanoff/goated-prompter/issues/new/choose) for bugs and feature requests; report vulnerabilities according to the [security policy](SECURITY.md).

### Checkpoint privacy and recovery

Dataset runs are not saved to disk. Runtime checkpoints, live request/response logs and interrupted partial-text diagnostics remain RAM-only. Active jobs are never deleted by cleanup. Shutdown uses bounded cancellation, marks unfinished work interrupted and releases RAM diagnostics. Files left by retired Dataset features (`dataset_checkpoints.json`, `idea_fingerprints.json`, the `dataset_v2_runs/` folder and the old private vocabulary file) are no longer read and can be deleted.

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

The reusable quality corpus, synthetic replay examples, annotation rubric and JSON/Markdown reporting live in **[`tests/eval/`](tests/eval/README.md)**. It covers Builder and MiniMax, including temporal/reference behavior, specialized domains, constraints and five-run novelty probes. Fidelity, useful detail density and semantic repetition require explicit review; missing annotations never count as success. CI publishes synthetic replay reports without inference; these check evaluation contracts, not model quality. Recorded outputs and review notes stay in ignored storage. Live evaluation requires an explicit existing engine and `--allow-live`; notify the GPU owner first.

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
