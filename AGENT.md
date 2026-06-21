# Agent Working Rules

These rules are mandatory for future work in this repository.

## Documentation Discipline

- After every prompt-driven implementation or code change, review whether project documentation must be updated.
- If the change affects behavior, architecture, runtime flow, debugging, configuration, testing, or operations, update the relevant files in `docs/`.
- Documentation updates must be complete, current, and consistent with the actual codebase.
- Do not leave documentation stale when the code has changed.

## Testing Discipline

- Always add or update automated tests when it is reasonably possible.
- Prefer focused regression tests for the exact behavior being changed.
- If a change cannot be covered by an automated test, state the gap explicitly in the final report.

## Verification Discipline

- After completing any meaningful change, run real verification commands, not only static reasoning.
- Prefer the smallest reliable command set first, then broaden if needed.
- Typical verification includes `pytest`, targeted tests, compile checks, or other real runtime validation appropriate to the change.
- Do not stop after implementation until verification has been executed and the result is understood.
- If verification fails, continue debugging and fixing until the system is working correctly or a real external blocker is identified.
- Do not conclude work until you are confident the change behaves correctly.

## Runtime Refresh Discipline

- After completing code changes, bring up or restart the relevant local service when that is needed for the changes to actually take effect.
- For this repository, prefer restarting the affected Docker Compose service or the directly relevant runtime entrypoint.
- Do not assume that tests alone are sufficient when the user expects the running service to pick up the latest code.
