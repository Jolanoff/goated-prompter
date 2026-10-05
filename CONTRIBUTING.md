# Contributing to Goated Prompter

Thanks for helping improve Goated Prompter. Bug reports, documentation fixes, regression tests, and focused code changes are welcome. Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Before you start

- Search [existing issues](https://github.com/Jolanoff/goated-prompter/issues) and pull requests before opening a new one.
- Use the bug report or feature request form. For bugs, include a minimal reproduction, the app commit/version, environment, backend, and relevant model/projector filenames.
- Discuss substantial workflow, storage, dependency, or architecture changes in an issue first.
- Report vulnerabilities using the [security policy](SECURITY.md), not a public bug report.
- Remove API keys, private prompts/images, personal paths, and user data from everything you share.

## Development setup

Follow the [installation guide](README.md#installation) for prerequisites and backend configuration. The project uses Python 3.10+ (3.12 recommended) and Node.js 22.12+ (20.19+ is also supported).

Fork the repository, clone your fork, and create a branch from the latest `master`. Run these commands from the project root in Windows PowerShell:

```powershell
git switch master
git pull --ff-only
git switch -c fix/short-description
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
npm --prefix frontend ci
npm --prefix frontend run build
```

On Linux/macOS, use `python3` to create the environment and `.venv/bin/python` instead of `.\.venv\Scripts\python.exe`.

Copy `config/config.example.json` to `config/config.json`. For text-only UI and plumbing work without model downloads or a GPU, use `{"backend": "mock"}` in your local config. The mock backend does not evaluate prompt quality or perform semantic rewriting.

Run the backend and frontend in separate terminals:

```powershell
.\.venv\Scripts\python.exe local_app.py
```

```powershell
npm --prefix frontend run dev
```

Open **http://127.0.0.1:5173**. Vite proxies `/api` to the backend on port 8190. Restart Python after backend or prompt-instruction changes.

## Project conventions

- Follow the surrounding Python and React code; keep changes focused and avoid unrelated formatting.
- Prompt instructions and target adapters belong in `goated_prompter/prompting/`; React workflow views belong in `frontend/src/workflows/`. See [module boundaries](docs/refactoring.md#module-boundaries).
- Preserve stored option IDs, API contracts, reference numbering, cancellation, revision checks, and atomic persistence. Explain any compatibility or migration changes.
- Add regression tests for fixes. For prompt changes, distinguish deterministic/mocked checks from evidence collected with a real model.
- Keep model weights, llama.cpp binaries, local config, `.env` files, `data/`, logs, generated assets, and private evaluation reports out of Git. Sanitize reusable fixtures. See [repository hygiene](docs/refactoring.md#what-belongs-in-git).
- Do not run model downloads, paid inference, or shared-GPU evaluation without the resource owner's approval.

## Verification

Run the relevant checks before submitting a pull request:

```powershell
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
.\.venv\Scripts\python.exe -m unittest discover -s tests
node --test tests/test_comfy_frontend.cjs tests/test_ui_shared.cjs
```

Build before Python tests so built-site checks can exercise the compiled assets. For UI/workflow changes, also run the [isolated browser tests](README.md#development-and-verification). Put your virtual environment's Python on PATH in that terminal, install Chromium once, and run:

```powershell
npm --prefix frontend exec -- playwright install chromium
npm --prefix frontend run test:e2e -- --config e2e/isolated.config.js
```

On Windows, an installed Edge can be used instead of downloading Chromium by setting `$env:PLAYWRIGHT_CHANNEL = "msedge"` before the test command. Isolated tests use temporary data and ports 8191/5191; they refuse to reuse running servers.

CI runs lint, frontend/Python tests, builds, frozen quality replay, ComfyUI JavaScript tests, and Chromium workflows. Mock and frozen-replay tests are not proof of live-model fidelity or GPU performance. For evaluation guidance, see [the quality corpus](tests/eval/README.md).

For documentation-only changes, check links, commands, spelling, and template syntax; explain why runtime tests were not needed.

## Submit a pull request

1. Target `master` and use a clear, focused title.
2. Explain the problem, solution, related issue, and user-visible impact.
3. List checks actually run and disclose skipped checks or remaining limitations.
4. Include screenshots for visual changes and sanitized examples for prompt behavior changes.
5. Update relevant documentation and tests; avoid committing generated files or private content.

## License

Contributions are accepted under the repository's existing [Goated Prompter Source-Available License](LICENSE). This is not an MIT-licensed project: selling the software or paid access to it is prohibited, while commercial outputs are permitted. Third-party code, assets, and model materials retain their own licenses; include appropriate attribution and only contribute material you have the right to share.
