# Schedule (draft, to review)

Submission closes Dec 4, 2:00 pm PT (Dec 5, 3:00 AM PKT). Target submit: **Dec 3**. Voice go/no-go: **Nov 28**, Voice effort capped at about 8 hours.

| Dates | Work | Exit criteria |
|---|---|---|
| Nov 16 to 17 | bootstrap, ledger-mcp implementation, remaining specs reviewed | bootstrap done, ledger core tasks 1 to 10 green |
| Nov 17 to 19 | library-mcp (corpus, index, hybrid retrieval, refusal, citations), ledger demo data and server | `answer_with_citations` works offline on committed subset |
| Nov 19 to 22 | brain (executor, conflicts, critic, provenance, API, SSE) with fake LLM | full demo briefing end to end with Ledger and Library, Oracle and Eyes as stubs |
| Nov 20 | first deploy dry run: VPS, DNS A record at name.com, Caddy HTTPS, GHCR pull | `https://stitch.aashirnoman.dev` serves a placeholder |
| Nov 21 to 24 | frontend (bench, map, briefing, states, RTL), eval dashboard shell | demo flows in the browser |
| Nov 23 to 25 | oracle (data, model, conformal, tool), training on Colab or Modal | forecast intervals with coverage eval |
| Nov 25 to 27 | eyes (train U-Net, ONNX, Sindh scene, tool) | segmentation on demo scene, Sen1Floods11 test IoU |
| Nov 27 to 28 | voice (Whisper, Azure TTS, pre-render) | **Nov 28 checkpoint**: end to end, or switch to pre-rendered audio |
| Nov 29 to 30 | polish: spooky animation, sound, accessibility, Urdu RTL, evals dashboard | Playwright smoke green |
| Dec 1 | deployment hardening, offline smoke test, THIRD_PARTY audit | clean-clone `docker compose up` works with network blocked |
| Dec 2 | write-up, demo video, bug fixes | write-up complete |
| Dec 3 | submit | |

Oracle and Eyes training can run on Colab or Modal in the background while other work continues. Start the Eyes training notebook early (by Nov 22) so GPU time is not on the critical path.
