# Local download audit — 2026-11-12

User requested analysis without repeating downloads after two Wi-Fi outages.
This audit used local files, package metadata, process inspection and the prior
tool transcript only. No new network requests, installations or downloads were
started during the audit. Local process checks, including the elevated execution
context, found no active project download processes.

## Verified current state

| Item | Evidence | Status |
| --- | --- | --- |
| uv | `.rag_state/tools/uv`, 37,991,656 bytes | Downloaded executable |
| Lockfile | `uv.lock`, 244,676 bytes, 127 package records | Resolution completed; retain it |
| Python environment | No installed distribution metadata under `.venv/lib/python3.10/site-packages` | Environment scaffold only; installation incomplete |
| uv cache | 385 files, 38,098,232 bytes | Preserve; not proof that all packages are cached |
| Extra wheel | `.rag_state/downloads/langchain_ollama-1.1.0-py3-none-any.whl`, 31,413 bytes | Downloaded, not installed |
| Ollama archive | `.rag_state/tools/ollama-linux-amd64.tar.zst`, 141,335,296 bytes | Partial, not a usable installation |
| BGE / Qwen weights | No project model directories found | Not downloaded into project state |

The official release metadata retrieved in the earlier attempt reported
1,545,767,640 bytes for the Ollama archive: the local partial file is 9.14% of
that expected size. That release metadata was not fetched again for this audit.
Disk sizes are not total network traffic: retries, compression and extraction
make those quantities different. The cache and partial archive must be retained.

## Problems in the previous procedure

1. Several `uv sync` attempts were launched, with curl and pip downloads also
   active during parts of the session. Some new attempts began without confirming
   that all previous attempts had exited.
2. Neither the large curl transfer nor the dependency manager had a configured
   bandwidth cap. Dependency download concurrency was not explicitly limited.
3. Connection failures led to repeated requests, alternate endpoints, and longer
   retry windows rather than reducing traffic first.
4. A roughly 1.55 GB Ollama distribution was selected. A locally examined archive
   listing included CUDA library directories, although the intended baseline
   uses CPU. Its size should have been assessed before beginning the transfer.
5. Diagnostic requests to multiple public servers added connections during the
   troubleshooting period. Successful IPv4 requests did not establish the root
   cause of the other connection failures.
6. Earlier README/baseline statements became stale when the lockfile was
   eventually produced, even though dependency installation remained incomplete.

These actions created avoidable network load and could have contributed to
congestion. There are no router logs or Wi-Fi interface diagnostics proving the
cause of the user's outages; no stronger causal claim is justified.

## Constraints for any later resumption

The latest user instruction takes precedence over the earlier blanket approval:
do not resume downloads as part of this audit. First retain and inspect the
existing cache, lockfile and partial archive; do not restart completed work.

If the user later requests resumption, use one download task at a time, cap its
bandwidth explicitly, and disable automatic retries initially. Limit dependency
download concurrency to one as well; concurrency alone is not a bandwidth cap.
Agree an appropriate bandwidth limit with the user before another large transfer.
Resume the existing archive only after checking server range support and artifact
identity. Do not launch another attempt until the previous process has exited.
Keep the CPU requirement and full download size visible before choosing the
remaining installation route. Do not change system DNS, routing or Wi-Fi settings.

## Resumption — 2026-11-13

The user authorized controlled, mostly sequential installation, then asked to
raise the initially conservative 256 KiB/s limit. Current cap: **2 MiB/s**, one
curl transfer at a time, zero automatic retries. SHA-256 checks use uv.lock for
packages, GitHub release metadata for Ollama, and registry layer digests for
Qwen. Runtime execution is offline.

Generated state, package cache, wheels, models and the virtual environment were
moved to `<state_dir>` outside OneDrive. This avoids
placing large changing artifacts in a potentially synchronized directory.
OneDrive synchronization was identified as a possible additional traffic source;
its activity was not independently confirmed. System network settings were not
changed. Partial files were retained through the move and the speed change.

Python dependencies are installed, `uv sync --locked --offline` passes, and all
21 tests pass, including real Chroma integration. Ollama/model downloads remain
in progress. Local operational helpers and logs are in the external runtime's
`tools/` directory and root. No new transfer should be launched until checking
its existing `controlled-download.lock` and current worker state.
