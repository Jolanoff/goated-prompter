# Goated Prompter

Goated Prompter is a model-aware image and video prompt node for ComfyUI.

## Local React App

The standalone frontend in `frontend/` uses React and Vite, with a dark, purple-accented layout inspired by the reference design. It uses the existing Python prompt pipeline. The original ComfyUI node and canvas interface remain available.

### Run Locally

Requires Python 3.10+ and Node.js 20.19+ or 22.12+ (a current Node LTS is recommended). From this project folder:

```powershell
python -m pip install -r requirements-local.txt
npm --prefix frontend install
npm --prefix frontend run build
python local_app.py
```

Open **http://127.0.0.1:8190**. After the first build, only `python local_app.py` is needed. The server binds to loopback, serves the built frontend, and does not require ComfyUI to be running. Fonts and UI assets are bundled locally.

Your existing backend configuration is reused; the app does not install or download an inference model. Open **Settings** in the sidebar, enter your **Models directory**, choose **Keep model loaded**, and click **Save settings**. The selected directory is scanned directly and recursively. Put each model GGUF and its matching `mmproj` GGUF in the same folder, for example:

```text
D:\ComfyUI\models\LLM\
  Qwen3.5-9B\
    Qwen3.5-9B-Q4_K_M.gguf
    mmproj-Qwen3.5-9B-BF16.gguf
```

For this example, select `D:\ComfyUI\models\LLM` (or the individual `Qwen3.5-9B` folder). **Prompt engine** automatically lists the complete discovered profiles. Incomplete pairs are reported in Settings rather than appearing as usable engines. Choose an engine in the builder; that selection is saved automatically. Refresh models rescans the saved folder after you add files.

The models directory, retention preference, and chosen engine are persisted on the server in **`data/settings.json`**, independently of browser storage, and survive app restarts. Model/runtime settings cannot be changed during an active or paused job. These settings affect only the standalone app, not the ComfyUI node configuration. Before settings are saved, the app uses the existing config/environment discovery defaults.

Prompt Builder values also autosave to the `builder` object in `settings.json`: idea, mode, target, creativity, prompt length, Director, Director behavior, workflow rules, all reference-source selections, current generated output, and output lock. The interface shows Saving, Saved, or a retryable error. Wait for Saved before closing the browser to guarantee the latest edits have reached disk; generation flushes pending edits first. Reopening restores the last saved builder draft, including a locked output if enabled. Image bytes and filenames are not saved.

Configure the llama-server executable in `nodes/goated_prompter/config.json`, or point `GOATED_PROMPTER_CONFIG` at your own configuration. The frontend uses the node's existing runtime defaults rather than exposing manual GGUF paths, context/token budgets, and GPU-layer overrides. The header reports the local API connection, not GPU readiness or a ComfyUI connection. An OpenAI-compatible backend still sends generation inputs to whichever endpoint you configure and does not require local model discovery.

### Behavior

- Existing generation modes, target models, creativity options, prompt lengths, Director presets, workflow rules, and preservation controls come from the node's schema. Local prompt engines come from the saved models folder.
- **Mode** defines the task; **Director** adds compatible specialist technique and style without changing that task; **Prompt length** controls descriptive density even when a Director prefers shorter or longer wording. Creativity and reference/preservation constraints still limit invention, and target-model output syntax remains required. These responsibilities apply to both grounded generation and text-only preview. Changing Mode does not replace the selected Director or clear its ComfyUI working copy.
- Upload **at most four images**, in stable Image 1 through Image 4 slots. Removing one does not renumber the others. Uploads are processed in memory, not saved in a gallery, and must be re-uploaded after reloading the page.
- **Preserve references** combines mapping and preservation into one control per attribute: **Off / Image 1 / Image 2 / Image 3 / Image 4 / Blend**. It covers subject, face/identity, outfit, pose, composition, camera, scene/environment, lighting, colors, mood/style, and materials. Off means no reference evidence or preservation for that attribute. An image selection strictly preserves that attribute from that source, independently of all other rows. Blend uses all uploaded images for the selected attribute and requires at least two. Missing restored sources are reported rather than silently reassigned.
- Linked selections take priority over conflicting wording and Director defaults. For example, a selected mood/style source is not discarded merely because the idea includes "cinematic". To freely change a preserved attribute, switch that row Off. Only selected sources are analyzed, and the final compiler receives resolved attribute evidence instead of raw images. Existing ComfyUI workflows retain their legacy Auto/Preserve behavior.
- **Generate prompt** uses the grounded pipeline for selected reference sources. Each click requests a fresh result unless output is locked. **Text-only preview** retains the canvas preview's behavior: it ignores images, reference mappings, and Preserve flags.
- **Maximum Detail** uses its detailed backend instruction and requests at least 3072 final-output tokens instead of the normal default 768, subject to available context. The legacy Maximum label maps to the same option. Evidence analysis keeps its existing budget. This is capacity, not a guaranteed word count: unsupported details are not invented to fill it. Known context limits are checked using a coarse input estimate, and token-limit truncation is reported as an error rather than presented as a completed prompt.
- **Maximum Detail Director** does not change the prompt-length setting or token budget. Select **Maximum Detail** under prompt length for the larger output capacity; **Short** still requests a compact result with that Director.
- **Lock output** returns the exact current prompt without inference. Copy, edit, clear, and Director Save As/Delete remain available. Model refresh, unload, and the saved retention preference are in Settings.
- **Pause / Resume** is cooperative, not cancellation or GPU process suspension. An active model call finishes before the next checkpoint pauses. The interface distinguishes Pause requested from Paused. Resume continues the same job without restarting completed stages. A paused model session may continue occupying VRAM. Refreshing the browser can recover an active job while the Python server remains running; restarting the server cannot recover inference state.
- **Save Prompt / Delete** stores named prompt text in **`data/prompts.json`**, with its target label and save date. This is separate from Director presets. No database or account is needed. All browsers accessing this server share the saved collection; clearing browser site data no longer deletes saved prompts. Images and the full generation settings are not included in saved prompts.

The app runs one generation at a time. It does not add accounts, templates, image generation, or a ComfyUI job queue.

### Local Data

Settings and prompts use human-readable JSON files in `data/`. Writes use a temporary file in the same directory followed by atomic replacement, so a failed write does not leave a partially written store. Invalid JSON is reported rather than silently discarded. To back up your setup and prompt library, back up `data/settings.json` and `data/prompts.json`. Stop the server before manually editing or restoring these files.

Existing SQLite settings migrate automatically on startup when `settings.json` does not yet exist. The old `settings.sqlite3` is left untouched as a backup; it is not used for ongoing storage once JSON exists.

Existing browser-saved prompts import automatically when you open the updated app from the browser and address where they were saved. The browser copy is removed only after the server confirms the exact imported records. Import failures retain the original browser data, and retries do not duplicate records. Open each previously used browser/address if you have separate old collections. Session storage is still used only for temporary generation-job recovery, not for settings or saved prompts.

### Frontend Development

Run the Python backend in one terminal and Vite in another:

```powershell
python local_app.py
```

```powershell
npm --prefix frontend run dev
```

Open **http://127.0.0.1:5173**. Vite proxies `/api` to port 8190. Use the default development ports unless you also update the proxy and backend trusted origins.

### Verification

```powershell
python -m unittest discover -s tests
node --test tests/test_frontend.cjs tests/test_ui_shared.cjs
npm --prefix frontend test
npm --prefix frontend run build
```

The Playwright tests start their own isolated mock backend and Vite server on ports 8190 and 5173; stop normal development servers first. Install a test browser once with `npm --prefix frontend exec -- playwright install chromium`, then run `npm --prefix frontend run test:e2e`. On Windows with Microsoft Edge already installed, use `$env:PLAYWRIGHT_CHANNEL = "msedge"` instead of downloading Chromium. The browser tests exercise desktop/mobile layouts, pause/resume, reload recovery, four reference slots, linked source controls, builder autosave and retries, text-only preview, exact locked output, JSON settings and prompt persistence, deletion, browser migration, and safe save retries. They do not validate real model quality or GPU inference.

This package is prepared for future GitHub, ComfyUI Registry, and ComfyUI-Manager publication, but it has not been published and no Registry availability is claimed.

## Included Nodes
- `GoatedPrompter` - Goated Prompter

## Installation

### Manual Installation
Copy or clone this folder as `ComfyUI/custom_nodes/goated-prompter`, then restart ComfyUI.

Enable only one copy of this package to avoid duplicate node and route registrations. Restart ComfyUI and fully reload the browser after installation.

### ComfyUI Manager
Manager/Registry installation is planned for a later phase after clean-install validation and metadata finalization.

## Workflow Compatibility
The internal node ID has changed to `GoatedPrompter`. Existing workflows must replace the previous node with `Goated Prompter` and reconnect its inputs and outputs. Widget fields and sockets retain their behavior, but frontend appearance and private state use new property names.

Backend code and local configuration live in `nodes/goated_prompter/`. The frontend is `web/goated_prompter/goated_prompter.js`, with drawing helpers in `web/shared/ui_shared.js`. API routes use `/goated-prompter/v1/`.

Configuration is loaded from `GOATED_PROMPTER_CONFIG` when set, otherwise from `ComfyUI/user/GoatedPrompter/config.json` when present, then from `nodes/goated_prompter/config.json`. User Directors default to `ComfyUI/user/GoatedPrompter/directors`; override this with `GOATED_PROMPTER_USER_DIR`. Existing user files are not migrated automatically. Set `GOATED_PROMPTER_DEBUG_PROMPTS=1` only when full prompt diagnostics are needed.

## Dependencies
No extra pip packages are currently required beyond a normal ComfyUI runtime. See `requirements.txt`.

## Goated Prompter — Director AI iteration

`Goated Prompter` turns a rough image or video idea into a model-aware prompt. It supports text-only direction and an optional normal ComfyUI `IMAGE` socket for grounded VLM generation. With no IMAGE, the Generate button stores a text-only result in the hidden `generated_prompt` widget and queueing emits it as a normal `STRING`. With IMAGE connected, queue execution always calls a vision-capable backend and deliberately ignores the cached text-only preview.

The default installation has no globally imported LLM dependency and still loads safely. A `config.json` remains available for backend/runtime setup, but installed local model pairs can now be selected without editing model paths in that file.

### Director AI profiles

The compact `Director AI` control is independent of Mode, Target Model, and Creativity:

- `Default` selects the discovered Qwen3.5-9B standard profile.
- `Uncensored` selects the discovered Qwen3.5-9B HauhauCS aggressive profile.
- `Custom` exposes discovered generic folders and manual overrides inside Advanced.

Goated Prompter scans `ComfyUI/models/LLM` recursively. Each folder is treated as one profile: a non-`mmproj` GGUF is paired with an `mmproj` GGUF from the same folder. When several files exist, recommended quant names are preferred deterministically and the choice is reported as a warning. Incomplete folders remain visible under Custom but are marked as not vision-ready.

`Refresh` in Advanced clears the discovery cache and rescans immediately; ComfyUI does not need to restart when model files are added. Recognized Qwen profiles apply the maintained defaults `reasoning=off`, `image_min_tokens=1024`, `max_tokens=768`, `context_size=8192`, `gpu_layers=auto`, `keep_model_loaded=false`, and loopback host binding.

### Mock backend

Use this configuration to verify UI interaction, instruction assembly, routing, and STRING output without an LLM or network access:

```json
{
  "backend": "mock"
}
```

The Mock backend deliberately returns `[Mock Goated Prompter]` followed by the source idea; it does not simulate prompt intelligence.
The Mock backend is text-only. Connecting IMAGE while Mock is selected returns a clear capability error rather than silently ignoring the image.

### OpenAI-compatible backend

Any server exposing an OpenAI-compatible `/chat/completions` endpoint can be configured without an extra Python dependency:

```json
{
  "backend": "openai_compatible",
  "openai_compatible": {
    "base_url": "http://127.0.0.1:1234/v1",
    "model": "your-model-name",
    "api_key_env": "GOATED_PROMPTER_API_KEY",
    "temperature": 0.5,
    "timeout": 90
  }
}
```

Set the key in the environment that launches ComfyUI when the endpoint requires one. For example, use `$env:GOATED_PROMPTER_API_KEY="..."` in PowerShell or `export GOATED_PROMPTER_API_KEY="..."` in a POSIX shell. Local endpoints that do not require authentication may leave the variable unset. A different config location can be selected with `GOATED_PROMPTER_CONFIG`.

For IMAGE requests, Goated Prompter sends the user content as OpenAI-compatible `text` plus `image_url` content parts. The configured endpoint and selected model must actually support vision. The first image in a ComfyUI batch is converted to RGB PNG in memory, keeps its aspect ratio, and is reduced to a maximum edge of 1344 pixels by default. Adjust `vision.max_image_dimension` only when the VLM requires a different size.

### Local llama.cpp VLM backend

The optional `local_llama_cpp` backend launches the official `llama-server` executable directly with `shell=False`; it does not install or import a llama.cpp Python package. Current llama.cpp documents multimodal chat through `/v1/chat/completions`, using `--model` with a matching `--mmproj`. See the [official multimodal guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md) and [server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).

Recommended first model folder:

```text
ComfyUI/models/LLM/Qwen3.5-9B/
  Qwen3.5-9B-Q4_K_M.gguf
  mmproj-Qwen3.5-9B-BF16.gguf
```

Obtain a matching model/projector pair from the same trusted release. Goated Prompter requires both files, requires the projector filename to contain `mmproj`, and requires both to be in the same folder. It never guesses a projector from an unrelated model.

Example configuration:

```json
{
  "backend": "local_llama_cpp",
  "vision": { "max_image_dimension": 1344 },
  "local_llama_cpp": {
    "model_path": "LLM/Qwen3.5-9B/Qwen3.5-9B-Q4_K_M.gguf",
    "mmproj_path": "LLM/Qwen3.5-9B/mmproj-Qwen3.5-9B-BF16.gguf",
    "llama_server": "C:/portable/llama.cpp/llama-server.exe",
    "host": "127.0.0.1",
    "port": 8189,
    "context_size": 8192,
    "reasoning": "off",
    "image_min_tokens": 1024,
    "max_tokens": 768,
    "gpu_layers": "auto",
    "keep_model_loaded": false,
    "startup_timeout": 180,
    "timeout": 180
  }
}
```

For Default and Uncensored, discovered profile paths replace the example `model_path` and `mmproj_path` automatically. The explicit paths remain the legacy fallback and Custom/manual path. Paths are resolved relative to ComfyUI's real models directory through `folder_paths`. `models_dir` or `GOATED_PROMPTER_MODELS_DIR` can be used only when running outside a normal ComfyUI environment. `llama_server` may be an absolute/relative executable path or a command available on `PATH`.

The server binds to loopback only. Goated Prompter waits on llama.cpp's `/health` endpoint and sends the request only after the model is ready. With `keep_model_loaded: false` (default), the owned child is terminated after generation to release VRAM. With it enabled, the same owned server is reused. On ComfyUI/Python exit, all remaining children owned by Goated Prompter are cleaned up. Existing user-started llama.cpp processes are never reused or terminated; an occupied configured port produces an error.

### Multimodal execution and UI limitation

Connected IMAGE tensors exist only during queued graph execution. The canvas Generate button therefore remains an honest text-only preview: when IMAGE is connected, its status explicitly says to queue the graph for image grounding. It does not inspect upstream graph state or fake VLM output. Queue-time execution has priority and always regenerates from IMAGE even if a text preview is cached.

Mode-specific grounding is applied for Archviz, Image Edit, Photography, Video, and Dataset Caption. The instruction separates observed image content from requested changes and protects visible content unless the mode or user explicitly requests modification.

### Manual local installation

1. Install a current official llama.cpp build containing `llama-server`.
2. Place the matching model and mmproj files together under `ComfyUI/models/LLM/Qwen3.5-9B/`.
3. In `nodes/goated_prompter/`, copy `config.example.json` to `config.json` if no configuration exists, and configure `llama_server` only if it is not already on `PATH`.
4. Select Default, Uncensored, or Custom in the node. Model/mmproj paths are discovered from the folder pair.
5. Restart ComfyUI so the updated node and route load.
6. Add `Goated Prompter`, optionally connect an IMAGE, enter direction, and queue the graph.
7. Connect its `prompt` STRING output to the normal prompt-consuming node in the workflow.

## Versioning
The optional Goated Prompter setup executable is versioned separately from this package release.

Future versioning model:
- PATCH: bugfixes that preserve workflows.
- MINOR: backward-compatible features or new nodes.
- MAJOR: breaking workflow/API changes.

## License
TODO: choose and add final license text before publication.
