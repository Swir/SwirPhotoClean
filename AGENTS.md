# SwirPhotoClean development

Build a Polish Windows photo duplicate finder. Do not claim release readiness without evidence.

- Never test disposal using personal photos. Generate fixtures in temporary directories.
- No permanent deletion, automatic bulk selection, registry cleaning or silent destructive actions.
- Keep at least one verified surviving file per affected group. Revalidate file content before recycling.
- Similarity is heuristic and must be labelled separately from exact duplicates.
- Keep Tk calls on the GUI thread; scanning and disposal must be cancellable workers.
- Run `python -m unittest discover -s tests -v` after meaningful changes. Build and smoke-test the packaged app before release.
- Document known limitations and remaining acceptance checks in STATUS.md. Do not repeatedly make cosmetic commits just to show activity.
- Stop the hourly heartbeat when acceptance criteria are met. Notify only material progress or a blocker that needs the user.
