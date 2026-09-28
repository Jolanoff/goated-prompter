# Goated Prompter

**Turn a rough idea and reference images into a prompt for your image or video model.**

Goated Prompter is a local web app with a React + Tailwind interface and a Python backend. It uses a language/vision model to write prompts, with controls for task, target model, creativity, detail, and which parts of your reference images to keep.

ComfyUI is **not required** to use the website. The app produces prompt text that you can copy into your preferred generation tool.

## Features

- **Text or image-guided prompts:** describe an idea, upload up to four reference images, or combine both.
- **Independent reference controls:** keep a face from Image 1, a pose from Image 2, a scene from Image 3, and lighting from Image 4. Blend can combine an attribute from all uploaded images.
- **Task-specific direction:** prompt enhancement, photography, architecture, characters, products, image editing, style transfer, dataset captions, and video shots.
- **Target-aware output:** supports Generic, Anima, Krea 2, FLUX.2 Klein, Z-Image, Qwen Image, Qwen2.1, MiniMax, LTX 2.5, and Ideogram4. Target selection changes the writing instructions/output format; it does not download or run that image/video model.
- **Reusable instruction presets:** choose a built-in preset, edit its instructions, or create your own.
- **Local prompt library:** autosaved builder settings, named saved prompts, and copy/edit controls.
- **Refine tab:** targeted revisions, quick editing actions, detail locks, before/after highlighting, manual edits, and persistent undo/redo with branching version history.
- **Explore tab:** compare Faithful, Creative, and Experimental directions, then send a favorite into Refine. Completed directions are saved even if a later direction fails or is cancelled.
- **MiniMax H3 tab:** a dedicated prompt-writing workflow with 4–15-second clip timing, automatic reference-role analysis, official H3 output schemas, and shared Director presets.
- **Dataset tab:** generate 1–25 trigger-prefixed prompts from user-led rules and guided inputs, with optional advanced coverage planning, automatic quality diagnostics, a model-assisted consistency review, and TXT/JSONL export.
- **Persistent creative settings:** Refine and Explore autosave their inputs and controls, offer independent advanced instruction editors, and save results directly to Saved Prompts.
- **Local inference through llama.cpp**, with an optional OpenAI-compatible endpoint.
- **End generation** to cancel an active local llama.cpp job.

### Target models

The Target model menu includes: Generic, Anima, Krea 2, FLUX.2 Klein, Z-Image, Qwen Image, Qwen2.1, MiniMax, LTX 2.5, and Ideogram4.

### Qwen2.1 target

Qwen2.1 uses writing guidance from the official [text-to-image](https://github.com/QwenLM/Qwen-Image-2.1/blob/main/prompt_rewrite/prompts/system_prompt_t2i.txt) and [image-editing](https://github.com/QwenLM/Qwen-Image-2.1/blob/main/prompt_rewrite/prompts/system_prompt_edit.txt) prompts, with **plain prompt text** as the app's output:

- **Text only:** an observer-style description of the finished image.
- **Selected image references:** an actionable editing directive grounded in the selected image evidence.

JSON metadata is not required. If a model still returns the upstream JSON envelope, the app extracts `rewritten_prompt` for editing, copying and saving.

All Qwen2.1 detail levels (Short, Medium, Detailed and Maximum Detail) use uncapped requests, including image evidence analysis, Builder, Refine, Explore and format repairs. Length controls writing detail rather than cutting off output. Local llama.cpp receives `max_tokens: -1`; remote requests omit `max_tokens`. Model context capacity and server-side limits still apply.

## MiniMax H3 prompt builder

Open **MiniMax H3**, choose **Clip Length** (10 seconds by default), leave **Mode** on Auto, and describe your video. Choose **MiniMax Director** or any existing instruction preset for creative direction.

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
- MiniMax analysis, prompt writing, and repair requests have no application output-token cap. Local llama.cpp runs until EOS (`max_tokens: -1`); remote OpenAI-compatible requests omit `max_tokens`. Engine context capacity and provider-side limits still apply.

This page writes **prompt text only**. It does not upload/analyze media, render videos, or call MiniMax's video-generation API. It requires a configured language-model prompt engine; the generic mock backend is for plumbing tests and does not perform H3 semantic rewriting.

## Installation

The walkthrough below uses **Windows PowerShell**. Download the app, llama.cpp, and the model separately; model weights are not included in this repository.

### 1. Install prerequisites

| Requirement | Download / notes |
| --- | --- |
| Python | [Python downloads](https://www.python.org/downloads/) — Python **3.10+**, with **3.12 recommended**. Enable **Add Python to PATH** on Windows. |
| Node.js + npm | [Node.js downloads](https://nodejs.org/en/download) — use a current LTS release, **22.12+**. Node 20.19+ is also supported by this Vite version. |
| Git | [Git downloads](https://git-scm.com/downloads) — optional if you download the repository ZIP instead. |
| llama.cpp | A current build containing **`llama-server`**, with support for your chosen vision model. See step 3. |

**Hardware:** inference memory and speed depend on the model, quantization, context size, and llama.cpp backend. The example model files total about **6.6 GB on disk**; runtime RAM/VRAM use is higher. A supported GPU is recommended. This project does not currently publish a benchmarked minimum-VRAM requirement.

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

### 5. Configure the executable and start the website

Open **`config/config.json`** and set `local_llama_cpp.llama_server` to your actual executable path. Use forward slashes or escaped backslashes in JSON:

```json
"llama_server": "C:/Tools/llama.cpp/llama-server.exe"
```

Leave `"backend": "local_llama_cpp"` selected. If `config.json` is absent, copy `config/config.example.json` to `config/config.json` first. The example uses `llama-server` on PATH; an absolute path is usually easier on Windows. You do not need to hand-edit `model_path` or `mmproj_path` for an engine selected through the website.

The shipped local defaults use `context_size: 32768` and `max_tokens: 4096`. Dataset generation remains EOS-driven (`max_tokens: -1`) and can use the larger context when needed. A 32K context consumes more RAM/VRAM than 8K; lower `context_size` if your hardware cannot load it. Restart the app (and unload any retained model) after changing runtime settings so llama.cpp starts with the new context.

Start the app from the project folder:

```powershell
.\.venv\Scripts\python.exe local_app.py
```

Open **http://127.0.0.1:8190** and keep the terminal running.

1. Open **Settings** in the sidebar.
2. Set **Models directory** to `D:\AI\Models` for the layout above.
3. Click **Save settings**, then **Refresh models** if needed. The saved directory is scanned directly and recursively; an `LLM` subfolder is not required.
4. Return to **Prompt Builder** and choose the discovered **Prompt engine**.
5. Enter an idea, start with **Medium** prompt length, and click **Generate prompt**.

The first generation loads the model and can take longer. **Keep model loaded** retains it between generations; otherwise the app releases its owned server after the operation. **Unload model** is available in Settings.

On later launches, you only need `.\.venv\Scripts\python.exe local_app.py` and the browser. After updating frontend source, run `npm --prefix frontend ci` and `npm --prefix frontend run build` again.

<details>
<summary>Linux / macOS command equivalents</summary>

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
| **Creativity** | Controls how much new visual detail the writer may introduce. |
| **Prompt length** | Controls descriptive density. Maximum Detail requests a larger output budget, not a guaranteed word count. |
| **Prompt engine** | The language/vision model that actually writes the prompt. |
| **Keep from reference images** | Selects the source for each attribute you want to preserve. |
| **Workflow rules / notes** | Adds constraints for the current request. |

### Four reference images

Each attribute—subject, face/identity, outfit, pose, scene, composition, camera, lighting, colors, materials, and mood/style—has its own source:

- **Off:** no reference evidence or preservation lock for that attribute.
- **Image 1–4:** keep that attribute from the selected image.
- **Blend:** use all uploaded images for that attribute; requires at least two images.

Only selected source images are analyzed. Their evidence is combined by attribute before the final prompt is written. A selected source lock takes priority over conflicting request wording; switch the attribute **Off** when you want to change it freely.

Slots keep their numbers when an image is removed. Removing a required image resets unavailable selections to **Off**. Images and filenames are not saved, so after reloading the page you must re-upload images and reselect their attributes.

### Output and generation

- **Text-only preview** ignores all reference images and preservation selections.
- **End generation** cancels the local job. With the managed llama.cpp backend it stops the owned server, so the next job reloads the model. An external OpenAI-compatible request currently ends at its next checkpoint rather than aborting the remote computation immediately.
- One generation runs at a time. Settings and preset editing are locked while a job is active.
- **Save Prompt** adds named output text to the saved-prompt library. Instruction presets are a separate library.

The app writes prompts; the quality and faithfulness of the generated description depend on your chosen model and inputs. It does not generate images or videos itself.

### Refine and version history

Open **Refine** from the sidebar or **Refine & history** under Builder output. Successful website Builder generations are automatically recorded in history. To work on an edited Builder output or another prompt, expand **Start from another prompt**, import the Builder text or paste a prompt, and choose its target model.

1. Enter the change you want, or use a quick action such as **Wider shot**, **Shorten**, or **Remove filler**.
2. Select **Keep these details** locks. These refer to facts in the source prompt; locked attributes take priority over conflicting edits. Unrelated details are preserved by the refinement instructions.
3. Click **Refine prompt**. The original and new version are saved separately, including the requested changes and locks.
4. Expand **What changed** for added/removed text. Use **Undo**, **Redo**, or select any version in history. Refining an older version creates a branch and keeps the previous branch available.
5. **Edit text → Save as new version** records a manual revision. **Save prompt** saves the current version directly to Saved Prompts with its target. **Use in Builder** transfers it back to Builder for further work.

Undo follows the current version's parent; each imported starting prompt or Builder generation begins a new history chain. History selection can restore any chain. The text diff uses bounded work and falls back to highlighting a larger changed region for very large prompts.

### Explore three directions

Open **Explore**, import a Builder prompt/idea or the current refinement, or enter new text. Choose a target model, direction length, and any detail locks, then click **Explore three directions**:

- **Faithful:** clarifies the source while retaining its staging and aesthetic.
- **Creative:** explores compatible, unspecified presentation choices while keeping the source's stated subjects, setting, action and medium.
- **Experimental:** explores bolder framing, perspective or rendering treatment of the same scene within those constraints. It does not request an unrelated new scene or arbitrary surreal elements.

The three calls run sequentially inside one model session, avoiding simultaneous GPU jobs and repeated model loading between directions. Each direction starts from the original source. Later calls receive bounded plain-text excerpts of earlier directions for comparison only. **End generation** uses the existing cancellation mechanism. Every finished direction is saved immediately; partial comparisons remain available after cancellation, failure, or a server restart. Use the **Saved comparisons** selector to revisit them and **Refine this direction** to start from a favorite.

Only **Ideogram4** requests JSON output. Other targets return prompt text (including character tags for Anima). Before saving, the workflows remove simple JSON prompt wrappers without another inference call. Malformed or complex structured output gets at most one format-correction retry for that direction; if it still fails, earlier completed directions stay saved and an error is shown. Existing saved comparisons are not rewritten by this validation.

Both workflows use the selected prompt engine and target adapters with their own editing instructions. Each Explore card has **Save prompt**, which opens the shared naming dialog and saves that exact direction and target. They operate on text: to carry image-grounded details into them, generate a reference-guided prompt in Builder first. Model adherence to locks and the quality/distinctness of directions still depend on the selected engine.

Completed versions, history selection/redo, and comparisons live in **`data/workspace.json`**. Writes are atomic and revision-checked so a stale browser tab cannot overwrite newer workspace edits. Storage limits are 1,000 versions, 100 comparisons, and 16 MiB for the workspace file; copy/back up useful results before clearing history or deleting older comparisons. If saving a generated result fails, its recovered text is shown for copying in the current session.

### Saved creative settings and advanced instructions

Refine, Explore, MiniMax H3, and Dataset settings autosave separately to **`data/workflow_settings.json`**. Refine retains requested changes, locks, starting text/target and manual-edit drafts; Explore retains its source text, target, length, locks and comparison selection; MiniMax and Dataset retain their workflow-specific inputs and current results. Wait for the respective **Saved** indicator before closing or reloading. Failed writes keep the local draft and expose retry/reload actions; revision checks prevent a stale browser tab from replacing newer settings.

Expand **Refine advanced settings** or **Explore advanced settings** to edit the built-in behavior. Refine has one system-prompt editor. Explore has separate editors for its system prompt and each of the three directions. **Save instructions** activates edits for subsequent generations; **Discard instruction edits** restores the saved editor text; **Use built-in instructions** resets that workflow to its shipped defaults. Unsaved instruction-editor changes require an explicit save before reload, unlike the ordinary autosaved controls.

Custom workflow instructions replace the corresponding built-in behavior. Target formatting and detail locks are still applied separately, including JSON validation for Ideogram4. Instruction changes are blocked during generation, and each job uses a snapshot of the saved instructions. Builder's instruction-preset library stays independent of these workflow-specific editors.

### Dataset prompt batches

Open **Dataset** and enter the exact trigger/prepend token, choose what it represents, and describe the traits that must remain consistent. Character batches preserve identity while varying pose, expression, framing and scene; style batches vary subject matter while preserving the visual language. Object, brand/logo, typography/text and custom concepts use their own consistency rules.

Choose 1–25 prompts, a realistic or non-realistic visual treatment, variety level, Director preset, target model and prompt length. **Concept-led variations** develops compatible presentations inside your concept and consistency rules. **Guided inputs** uses one line per scene idea and cycles those lines with new presentations when the batch is larger.

**Advanced coverage planning is optional and off by default.** With it off, the model follows your concept, consistency rules, and guided inputs without receiving automatic pose, action, expression, setting, or lighting assignments. This is the recommended mode for a tightly directed theme such as romance or a specific activity.

When explicitly enabled, the Coverage planner assigns category-specific axes before inference—for example framing, viewpoint, pose, expression, lighting and setting for characters. Focused, Balanced and Wide select progressively more axes; you can override those choices, preview the complete matrix, and reshuffle it with a persisted seed. Planned facets remain subordinate to the user's concept and rules. Disabling planning preserves an existing matrix for later but excludes it from generation.

Generation runs sequentially in one model session. Completed items appear while the batch runs and are retained in the current Dataset draft if a later item is stopped or fails. Results are editable and can be copied together or downloaded as TXT or JSONL. For Ideogram4, the trigger starts `high_level_description` so the outer JSON remains valid.

After generation, the local **Dataset quality report** checks completion, exact trigger placement, target formatting, leaked planning markers, unusual lengths, repeated openings, exact/near duplicates, and guided-input assignments without another model call. Planned coverage is scored only when the optional planner is enabled. **Deep consistency review** is optional: it asks the selected prompt engine to inspect bounded groups of four prompts for identity/style drift, constraint conflicts and target usability. It uses a fixed 2,048-token output budget per group. Both the plan and report autosave with the Dataset draft; editing a prompt invalidates and recomputes the deterministic report.

## Project and data layout

```text
goated-prompter/
├── local_app.py                 # Website launcher and local HTTP API
├── requirements-local.txt      # Standalone Python dependencies
├── config/
│   ├── config.example.json     # Portable configuration template
│   └── config.json             # Backend / llama-server configuration
├── goated_prompter/
│   ├── prompt_catalog.py       # Task, target, creativity, length and general prompts
│   ├── presets.py              # Built-in instruction presets and library management
│   ├── core.py                 # Prompt assembly and generation orchestration
│   ├── prompt_workflows.py     # Isolated refinement/exploration instructions and inference
│   ├── workflow_prompts.py     # Editable built-in workflow behavior
│   ├── workflow_settings.py    # Per-workflow drafts and instruction overrides
│   ├── workspace_api.py        # Creative-workspace endpoints and shared-job integration
│   ├── workspace_store.py      # Atomic versions, branching undo/redo and comparisons
│   ├── reference_map.py        # Attribute-to-image source mapping
│   ├── evidence.py             # Image analysis and resolved scene evidence
│   └── backends/               # llama.cpp and OpenAI-compatible clients
├── frontend/
│   ├── src/                    # React UI, Tailwind utilities and presentation labels
│   │   └── workflows/          # Separate Refine/Explore tabs, history and workspace state
│   └── dist/                   # Generated by npm run build; not committed
├── data/                       # Created as you save; not committed
│   ├── settings.json           # Settings and autosaved builder draft
│   ├── prompts.json            # Saved prompt collection
│   ├── workspace.json          # Versions, undo/redo and saved direction comparisons
│   ├── workflow_settings.json  # Refine/Explore drafts and custom instructions
│   └── directors/              # Custom instruction presets
│       └── .overrides/         # Edits to built-in instruction presets
├── tests/                      # Python and optional canvas tests
└── comfyui_web/                # Optional ComfyUI integration assets
```

Keep downloaded models and llama.cpp outside this source tree, as in the installation examples. Back up **`data/` and your configuration** to preserve your setup. Wait for the builder's **Saved** status before closing; stop the server before manually editing its JSON stores.

The website binds to loopback only. With the local backend, inference runs on your machine and UI assets/fonts are bundled locally. Configuring a remote OpenAI-compatible endpoint sends generation inputs, including selected images, to that endpoint.

Existing SQLite settings and browser-saved prompt collections have migration paths. A browser collection is imported when you revisit its original browser/address; the original copy is retained if importing fails.

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

`GOATED_PROMPTER_CONFIG` selects an alternative config file. Configuration otherwise uses the ComfyUI user config when available, then `config/config.json`. `GOATED_PROMPTER_USER_DIR` overrides instruction-preset storage. `GOATED_PROMPTER_DEBUG_PROMPTS=1` enables full prompt diagnostics in the server console.

## Development and verification

For live frontend edits, run the backend in one terminal and Vite in another, from the project root:

```powershell
.\.venv\Scripts\python.exe local_app.py
```

```powershell
npm --prefix frontend run dev
```

Open **http://127.0.0.1:5173**. Vite proxies `/api` to the backend on port 8190.

Static prompt content is in **`goated_prompter/prompt_catalog.py`**. Restart Python after editing it. Keep saved option keys stable. For new tasks, add both the option and its adapter; Director recommended-mode validation also lives in `presets.py`. Website-only display names/order live in `frontend/src/App.jsx` and `frontend/src/presetPresentation.js`.

Run the checks from the project root:

```powershell
npm --prefix frontend run build
.\.venv\Scripts\python.exe -m unittest discover -s tests
node --test tests/test_comfy_frontend.cjs tests/test_ui_shared.cjs
npm --prefix frontend test
```

Building first also enables `tests/test_built_site.py`, which checks that Python serves the compiled assets and completes a mock generation with fresh temporary storage.

Browser tests use a delayed mock backend and temporary settings, prompts, and preset storage. To make `python` resolve to your virtual environment for Playwright, activate it in the test terminal or put `.venv/Scripts` on that terminal's PATH. Install Chromium once using `npm --prefix frontend exec -- playwright install chromium`, then run:

```powershell
npm --prefix frontend run test:e2e -- --config e2e/isolated.config.js
```

On Windows with Edge installed, use `$env:PLAYWRIGHT_CHANNEL = "msedge"` before the test command instead of downloading Chromium. The isolated configuration uses ports **8191/5191** and refuses to reuse an existing server.

Automated checks cover prompt assembly, reference mapping, API/storage behavior, and browser workflows. Mock tests do not measure real-model output quality, GPU compatibility, or performance. Report issues with your OS, Python/Node versions, llama.cpp build/backend, exact model/projector filenames, and the relevant error at [GitHub Issues](https://github.com/Jolanoff/goated-prompter/issues).

## Optional ComfyUI integration

The original node remains available under the stable ID `GoatedPrompter`. To use it, place one copy of this repository at `ComfyUI/custom_nodes/goated-prompter`, configure the backend, and restart ComfyUI and reload its browser. The node exposes four optional IMAGE sockets and a prompt STRING output. Queue the graph for image-grounded generation; the canvas preview button is text-only.

The website remains the main installation path. There is no claimed ComfyUI Registry/Manager listing or bundled desktop installer. Installing only the Python package does not build or bundle the website.

## License and credits

[MIT License](LICENSE) — copyright (c) 2026 Jolanoff.

Built with React, Tailwind CSS, Vite, aiohttp, Pillow, and llama.cpp. Downloaded models and third-party dependencies retain their own licenses; model weights are not distributed with this project.
