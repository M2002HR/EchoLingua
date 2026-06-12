# EchoLingua Agent Instructions

- Work directly on the current branch unless the user explicitly requests a PR.
- Do not create pull requests by default.
- Do not create separate branches unless the task is high-risk or the user explicitly asks for it.
- Commit directly to the current branch after tests pass.
- Use conventional commit messages.
- Always run:
  - `python -m compileall echolingua tests`
  - `pytest -q`
- If package installation fails due to network, proxy, or package-index issues, report it clearly and provide the exact command the user should run locally.
- Always include a Testing section in the final response.
- Always include manual verification commands when the task touches generated audio, manifest, SQLite, logs, providers, or config.
- Never make real network calls in unit tests.
- Use `FakeTTSProvider` and `FakeLLMProvider` for tests.
- `EdgeTTSProvider` is optional and must fail gracefully if `edge-tts` is not installed.
- AJIL integration must stay behind interfaces/config until explicitly implemented.
- All runtime config must be owned by EchoLingua, not submodules.
