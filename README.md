# Goated Prompter

**Turn a rough idea and reference images into a prompt for your image or video model.**

Goated Prompter is a local web app with a React + Tailwind interface and a Python backend. It uses a language/vision model to write prompts, with controls for task, target model, creativity, detail, and which parts of your reference images to keep.

ComfyUI is **not required** to use the website. The app produces prompt text that you can copy into your preferred generation tool.

## Features

- **Text or image-guided prompts:** describe an idea, upload up to four reference images, or combine both.
- **Independent reference controls:** keep a face from Image 1, a pose from Image 2, a scene from Image 3, and lighting from Image 4. Blend can combine an attribute from all uploaded images.
- **Task-specific direction:** prompt enhancement, photography, architecture, characters, products, image editing, style transfer, dataset captions, and video shots.
- **Target-aware output:** Generic, Krea 2, FLUX.2 Klein, Z-Image, Qwen Image, MiniMax, LTX 2.5, and Ideogram4. Target selection changes the writing instructions/output format; it does not download or run that image/video model.
- **Reusable instruction presets:** choose a built-in preset, edit its instructions, or create your own.
- **Local prompt library:** autosaved builder settings, named saved prompts, and copy/edit controls.
- **Refine tab:** targeted revisions, quick editing actions, detail locks, before/after highlighting, manual edits, and persistent undo/redo with branching version history.
- **Explore tab:** compare Faithful, Creative, and Experimental directions, then send a favorite into Refine. Completed directions are saved even if a later direction fails or is cancelled.
- **Local inference through llama.cpp**, with an optional OpenAI-compatible endpoint.
- **End generation** to cancel an active local llama.cpp job.

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
5. **Edit text → Save as new version** records a manual revision. **Use in Builder** transfers the selected output and target back to Builder for further work or saving to Saved Prompts.

Undo follows the current version's parent; each imported starting prompt or Builder generation begins a new history chain. History selection can restore any chain. The text diff uses bounded work and falls back to highlighting a larger changed region for very large prompts.

### Explore three directions

Open **Explore**, import a Builder prompt/idea or the current refinement, or enter new text. Choose a target model, direction length, and any detail locks, then click **Explore three directions**:

- **Faithful:** clarifies the source while retaining its staging and aesthetic.
- **Creative:** explores compatible, unspecified presentation choices while keeping the source's stated subjects, setting, action and medium.
- **Experimental:** explores bolder framing, perspective or rendering treatment of the same scene within those constraints. It does not request an unrelated new scene or arbitrary surreal elements.

The three calls run sequentially inside one model session, avoiding simultaneous GPU jobs and repeated model loading between directions. Each direction starts from the original source. Later calls receive bounded plain-text excerpts of earlier directions for comparison only. **End generation** uses the existing cancellation mechanism. Every finished direction is saved immediately; partial comparisons remain available after cancellation, failure, or a server restart. Use the **Saved comparisons** selector to revisit them and **Refine this direction** to start from a favorite.

Only **Ideogram4** requests JSON output. Other targets return prompt text (including character tags for Anima). Before saving, the workflows remove simple JSON prompt wrappers without another inference call. Malformed or complex structured output gets at most one format-correction retry for that direction; if it still fails, earlier completed directions stay saved and an error is shown. Existing saved comparisons are not rewritten by this validation.

Both workflows use the selected prompt engine and target adapters with their own editing instructions. They operate on text: to carry image-grounded details into them, generate a reference-guided prompt in Builder first. Model adherence to locks and the quality/distinctness of directions still depend on the selected engine.

Completed versions, history selection/redo, and comparisons live in **`data/workspace.json`**. Unsubmitted text in the new tabs stays in memory across tab switches; submit/save it before reloading. Writes are atomic and revision-checked so a stale browser tab cannot overwrite newer workspace edits. Storage limits are 1,000 versions, 100 comparisons, and 16 MiB for the workspace file; copy/back up useful results before clearing history or deleting older comparisons. If saving a generated result fails, its recovered text is shown for copying in the current session.

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
│   ├── workspace_api.py        # Creative-workspace endpoints and shared-job integration
│   ├── workspace_store.py      # Atomic versions, branching undo/redo and comparisons
│   ├── reference_map.py        # Attribute-to-image source resolution
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
| Maximum Detail reports insufficient context or truncation | Try Medium/Detailed first; reduce long instructions or adjust runtime budgets. Maximum Detail requests at least 3072 final-output tokens and needs input/context headroom. |
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
