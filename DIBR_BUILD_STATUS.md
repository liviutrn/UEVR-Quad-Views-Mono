# Manual-depth DIBR build status

Status is evidence-based. A `false` flag means the branch has no qualifying evidence for that milestone yet.

| Milestone | Status | Evidence boundary |
| --- | --- | --- |
| Exact v186.1 Build49 source base | Verified locally | `DIBR_RELEASE_BASE.json` records the release commit and pinned dependency commits. CI must verify tag identity and ancestry. |
| Windows production backend build | Not verified | No successful Windows Actions run for this branch yet. |
| DIBR CPU contracts | Not verified | No successful Windows Actions run for this branch yet. |
| DIBR production DX12 WARP output geometry | Not verified | The test must exercise the production DIBR draw path and read back measured eye output. |
| STALKER 2 live depth acquisition | Not verified | Candidate discovery/preview alone does not establish usable current depth. |
| Live RGB-depth producer/frame association | Not verified | Must be proven at the real producer and consumer boundary. |
| PSVR2 / SteamVR headset output, comfort and stability | Not verified | Requires an actual headset test. |
| DIBR performance or image-quality improvement | Not claimed | No measurement is available. |

The test artifact is emitted only after the pinned Windows build, CPU contracts, and DX12 WARP checks pass. A packaged artifact can upgrade those CI rows only. Live game and headset rows remain false until separate evidence is recorded.
