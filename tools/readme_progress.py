from __future__ import annotations

import argparse
import re
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "readme"
STATUS = ROOT / "STATUS.md"
HEADING = "## Warunki odbioru — do zakończenia przed 1.0"


def metrics() -> tuple[int, int, float]:
    text = STATUS.read_text(encoding="utf-8")
    if HEADING not in text:
        raise SystemExit("authoritative acceptance heading not found in STATUS.md")
    section = text.split(HEADING, 1)[1]
    match = re.search(r"\n## ", section)
    if match:
        section = section[: match.start()]
    done = len(re.findall(r"^- \[x\] ", section, flags=re.MULTILINE | re.IGNORECASE))
    open_items = len(re.findall(r"^- \[ \] ", section, flags=re.MULTILINE))
    total = done + open_items
    if total <= 0:
        raise SystemExit("acceptance checklist is empty")
    return done, total, done / total


def render() -> dict[str, str]:
    done, total, fraction = metrics()
    pct = fraction * 100
    pct_text = f"{pct:.1f}%"
    state = "COMPLETE" if done == total else "IN PROGRESS"
    card_fill = 1100 * fraction
    mini_fill = 700 * fraction
    card = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="190" viewBox="0 0 1200 190" role="img" aria-labelledby="title desc"><title id="title">SWIR PhotoClean 1.0 acceptance progress</title><desc id="desc">SWIR PhotoClean 1.0 acceptance gate is {pct_text} complete: {done} of {total} checklist items are verified.</desc><defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#02050A"/><stop offset="1" stop-color="#07111C"/></linearGradient><linearGradient id="fill" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#0088FF"/><stop offset="1" stop-color="#62E5FF"/></linearGradient><pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse"><path d="M28 0H0V28" fill="none" stroke="#62E5FF" stroke-opacity=".055"/></pattern><filter id="glow" x="-40%" y="-100%" width="180%" height="300%"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter><clipPath id="clip"><rect x="50" y="132" width="1100" height="24" rx="12"/></clipPath></defs><rect x="1" y="1" width="1198" height="188" rx="24" fill="url(#bg)" stroke="#62E5FF" stroke-opacity=".22"/><rect x="1" y="1" width="1198" height="188" rx="24" fill="url(#grid)"/><text x="50" y="42" fill="#62E5FF" font-family="Segoe UI,Arial,sans-serif" font-size="16" font-weight="700" letter-spacing="3">SWIR PROGRESS</text><text x="50" y="78" fill="#F4FAFF" font-family="Segoe UI,Arial,sans-serif" font-size="30" font-weight="800">SWIR PhotoClean</text><text x="50" y="106" fill="#8DA8B8" font-family="Segoe UI,Arial,sans-serif" font-size="15">1.0 acceptance gate</text><text x="1110" y="78" text-anchor="end" fill="#F4FAFF" font-family="Segoe UI,Arial,sans-serif" font-size="34" font-weight="800">{pct_text}</text><text x="1110" y="106" text-anchor="end" fill="#62E5FF" font-family="Segoe UI,Arial,sans-serif" font-size="14" font-weight="700">{state}</text><rect x="50" y="132" width="1100" height="24" rx="12" fill="#08131F" stroke="#62E5FF" stroke-opacity=".16"/><rect x="50" y="132" width="{card_fill:.3f}" height="24" rx="12" fill="url(#fill)" filter="url(#glow)" clip-path="url(#clip)"/><text x="50" y="178" fill="#8DA8B8" font-family="Segoe UI,Arial,sans-serif" font-size="13">Verified: {done} / {total}</text><text x="1150" y="178" text-anchor="end" fill="#8DA8B8" font-family="Segoe UI,Arial,sans-serif" font-size="13">Source: STATUS.md acceptance checklist</text></svg>\n'''
    mini = f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="82" viewBox="0 0 900 82" role="img" aria-labelledby="title desc"><title id="title">SWIR PhotoClean compact 1.0 acceptance progress</title><desc id="desc">The 1.0 acceptance gate is {pct_text} complete: {done} of {total} items verified.</desc><defs><linearGradient id="fill" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#0088FF"/><stop offset="1" stop-color="#62E5FF"/></linearGradient><clipPath id="clip"><rect x="170" y="25" width="700" height="20" rx="10"/></clipPath></defs><rect x="1" y="1" width="898" height="80" rx="18" fill="#02050A" stroke="#62E5FF" stroke-opacity=".22"/><text x="24" y="27" fill="#62E5FF" font-family="Segoe UI,Arial,sans-serif" font-size="12" font-weight="700" letter-spacing="2">SWIR ROADMAP</text><text x="24" y="54" fill="#F4FAFF" font-family="Segoe UI,Arial,sans-serif" font-size="19" font-weight="800">{pct_text}</text><rect x="170" y="25" width="700" height="20" rx="10" fill="#08131F"/><rect x="170" y="25" width="{mini_fill:.3f}" height="20" rx="10" fill="url(#fill)" clip-path="url(#clip)"/><text x="870" y="67" text-anchor="end" fill="#8DA8B8" font-family="Segoe UI,Arial,sans-serif" font-size="11">1.0 acceptance gate · {done} / {total} verified</text></svg>\n'''
    template = '''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="180" viewBox="0 0 1200 180" role="img" aria-labelledby="title desc"><title id="title">SWIR Progress template</title><desc id="desc">Reusable template only. Not project data.</desc><rect x="1" y="1" width="1198" height="178" rx="24" fill="#02050A" stroke="#62E5FF" stroke-opacity=".22"/><text x="50" y="48" fill="#62E5FF" font-family="Segoe UI,Arial,sans-serif" font-size="18" font-weight="700">SWIR PROGRESS TEMPLATE</text><text x="50" y="90" fill="#F4FAFF" font-family="Segoe UI,Arial,sans-serif" font-size="30" font-weight="800">TEMPLATE — NOT PROJECT DATA</text><rect x="50" y="120" width="1100" height="24" rx="12" fill="#08131F"/><text x="50" y="164" fill="#8DA8B8" font-family="Segoe UI,Arial,sans-serif" font-size="13">Populate only from an authoritative verified source.</text></svg>\n'''
    return {"progress-card.svg": card, "progress-mini.svg": mini, "progress-template.svg": template}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = render()
    for text in outputs.values():
        ET.fromstring(text)
        if "XXX" in text:
            raise SystemExit("invalid SVG placeholder")
    if args.check:
        stale = [name for name, text in outputs.items() if not (OUT / name).exists() or (OUT / name).read_text(encoding="utf-8") != text]
        if stale:
            raise SystemExit("stale progress assets: " + ", ".join(stale))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        status = STATUS.read_text(encoding="utf-8")
        if "assets/readme/progress-card.svg" not in readme or "assets/readme/progress-mini.svg" not in status:
            raise SystemExit("progress assets are not embedded in README/STATUS")
        print("progress assets are current")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in outputs.items():
        (OUT / name).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
