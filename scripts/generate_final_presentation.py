#!/usr/bin/env python3

import argparse
import os
import subprocess
from datetime import datetime
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE


# ---------- Styling helpers ----------

def hex_to_rgb(hex_str: str) -> RGBColor:
    s = (hex_str or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
        return RGBColor(r, g, b)
    except Exception:
        return RGBColor(47, 85, 151)  # default accent


def add_accent_bar(slide, color: RGBColor):
    try:
        bar = slide.shapes.add_shape(
            MSO_AUTO_SHAPE_TYPE.RECTANGLE, Inches(0), Inches(0), Inches(13.33), Inches(0.25)
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = color
        if bar.line:
            bar.line.fill.background()
    except Exception:
        pass


def style_title_shape(shape, color: RGBColor, size_pt: int = 44):
    if not shape or not hasattr(shape, "text_frame"):
        return
    tf = shape.text_frame
    for p in tf.paragraphs:
        p.alignment = PP_ALIGN.CENTER
        for r in p.runs:
            r.font.size = Pt(size_pt)
            r.font.bold = True
            r.font.color.rgb = color


def style_body_frame(tf, size_pt: int = 20):
    for p in tf.paragraphs:
        for r in p.runs:
            r.font.size = Pt(size_pt)
            r.font.color.rgb = RGBColor(60, 60, 60)


def add_footer(slide, text: str):
    if not text:
        return
    left = Inches(0.5)
    top = Inches(7.0)
    width = Inches(12.33)
    height = Inches(0.4)
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.clear()
    p = tf.paragraphs[0]
    p.text = text
    p.alignment = PP_ALIGN.RIGHT
    for r in p.runs:
        r.font.size = Pt(12)
        r.font.color.rgb = RGBColor(100, 100, 100)


# ---------- Slide helpers ----------

def add_title_slide(prs: Presentation, title: str, subtitle: str):
    slide_layout = prs.slide_layouts[0]
    slide = prs.slides.add_slide(slide_layout)
    slide.shapes.title.text = title
    slide.placeholders[1].text = subtitle
    return slide


def add_bullets_slide(prs: Presentation, title: str, bullets, level: int = 0):
    slide_layout = prs.slide_layouts[1]
    slide = prs.slides.add_slide(slide_layout)
    slide.shapes.title.text = title
    tx_box = slide.placeholders[1]
    tf = tx_box.text_frame
    tf.clear()

    first = True
    for item in bullets:
        if not item:
            continue
        if first:
            p = tf.paragraphs[0]
            first = False
        else:
            p = tf.add_paragraph()
        p.text = item
        p.level = level

    style_body_frame(tf)
    # make title smaller than cover
    try:
        style_title_shape(slide.shapes.title, hex_to_rgb(getattr(prs, "_accent", "#2F5597")), size_pt=36)
    except Exception:
        pass
    return slide


def add_title_only_slide(prs: Presentation, title: str, lines=None):
    slide_layout = prs.slide_layouts[5]  # Title Only
    slide = prs.slides.add_slide(slide_layout)
    slide.shapes.title.text = title

    if lines:
        left = Inches(1)
        top = Inches(2.0)
        width = Inches(8)
        height = Inches(3)
        tx_box = slide.shapes.add_textbox(left, top, width, height)
        tf = tx_box.text_frame
        tf.word_wrap = True
        tf.clear()
        for i, line in enumerate(lines):
            p = tf.add_paragraph() if i > 0 else tf.paragraphs[0]
            p.text = line
            p.level = 0
    return slide


# ---------- Builder ----------

def _maybe_formalize(enabled: bool, text: str) -> str:
    if not enabled:
        return text
    # Simple fallback formalizer: title case first letter and avoid slang
    t = text.strip()
    if not t:
        return t
    # Try OpenAI if available and key is set
    try:
        if os.getenv("OPENAI_API_KEY"):
            import openai  # type: ignore
            client = openai.OpenAI()
            prompt = f"Rewrite the following bullet in concise, professional, and plain English suitable for a pitch slide. Keep it under 18 words.\n\nBullet: {t}"
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role":"user","content":prompt}],
                temperature=0.2,
                max_tokens=60,
            )
            out = resp.choices[0].message.content.strip()
            return out or t
    except Exception:
        pass
    # Local heuristic formalization
    repl = {
        "wanna":"want to", "gonna":"going to", "kinda":"kind of", "sorta":"sort of",
        "u ":"you ", " btw":" by the way", " asap":" as soon as possible",
    }
    for k,v in repl.items():
        t = t.replace(k, v)
    if t and t[0].islower():
        t = t[0].upper() + t[1:]
    return t


def add_image_slide(prs: Presentation, title: str, image_path: str):
    slide_layout = prs.slide_layouts[5]  # Title Only
    slide = prs.slides.add_slide(slide_layout)
    slide.shapes.title.text = title
    # Place image centered with sensible margins
    left = Inches(0.75)
    top = Inches(1.4)
    width = Inches(11.8)
    try:
        slide.shapes.add_picture(str(image_path), left, top, width=width)
    except Exception:
        # fallback smaller width
        slide.shapes.add_picture(str(image_path), left, top, width=Inches(9.5))
    return slide


def render_mermaid_to_png(mmd_path: str, png_path: str) -> bool:
    try:
        cmd = ["mmdc", "-i", mmd_path, "-o", png_path]
        r = subprocess.run(cmd, check=True, capture_output=True)
        return os.path.exists(png_path)
    except Exception:
        return False

def svg_to_png(svg_path: str, png_path: str) -> bool:
    # Try Python cairosvg first, then fall back to inkscape CLI
    try:
        import cairosvg  # type: ignore
        cairosvg.svg2png(url=svg_path, write_to=png_path)
        return os.path.exists(png_path)
    except Exception:
        pass
    try:
        cmd = ["inkscape", svg_path, "--export-type=png", f"--export-filename={png_path}"]
        subprocess.run(cmd, check=True, capture_output=True)
        return os.path.exists(png_path)
    except Exception:
        return False

def _parse_icons_arg(arg: str) -> list[str]:
    parts = []
    for chunk in (arg or "").split(","):
        c = chunk.strip()
        if c:
            parts.append(c)
    return parts

def add_icons_bottom_right(slide, icon_paths: list[str]):
    # Place a row of small icons bottom-right, above footer
    if not icon_paths:
        return
    size = Inches(0.55)
    gap = Inches(0.12)
    # compute starting left so that icons end near ~12.6in
    count = min(6, len(icon_paths))
    total_w = count * size + (count - 1) * gap
    right_edge = Inches(12.6)
    left = max(Inches(0.5), right_edge - total_w)
    top = Inches(6.7)
    x = left
    from pathlib import Path as _P
    added = 0
    for p in icon_paths:
        if added >= count:
            break
        if not _P(p).exists():
            continue
        try:
            slide.shapes.add_picture(str(p), x, top, width=size)
            x += size + gap
            added += 1
        except Exception:
            continue

def add_icons_for_slide(slide, slide_num: int, args):
    # per-slide override, else global
    per = getattr(args, f"icons_s{slide_num}", "")
    icons = _parse_icons_arg(per) if per else _parse_icons_arg(getattr(args, "icons_global", ""))
    add_icons_bottom_right(slide, icons)

def build_deck(args):
    project_name = args.project_name or "Room Matcher AI"
    team = args.team or "RoomMatcher AI"
    members = args.members or "Ahmed Mustafa and Maira Anjum"
    tagline = args.tagline or "Minimal multi-agent roommate matcher & room listings search for Pakistan"

    prs = Presentation()
    prs._accent = args.accent
    accent_rgb = hex_to_rgb(args.accent)
    # Build footer text safely even if website is not provided
    footer_text = getattr(args, "footer", None) or getattr(args, "website", "") or project_name

    # Slide 1 — Title
    subtitle_lines = [tagline, f"Team: {team}", f"Members: {members}"]
    subtitle_lines.append(datetime.now().strftime("%b %d, %Y"))
    title_slide = add_title_slide(prs, project_name, "\n".join(subtitle_lines))
    # Optional background and logo
    if args.background:
        bp = Path(args.background)
        if bp.exists():
            title_slide.shapes.add_picture(str(bp), Inches(0), Inches(0), width=Inches(13.33), height=Inches(7.5))
    style_title_shape(title_slide.shapes.title, accent_rgb, size_pt=48)
    if args.logo:
        lp = Path(args.logo)
        if lp.exists():
            title_slide.shapes.add_picture(str(lp), Inches(11.8), Inches(0.35), width=Inches(1.2))
    add_footer(title_slide, footer_text)
    add_icons_for_slide(title_slide, 1, args)

    # Slide 2 — Why you chose the challenge
    s = add_bullets_slide(
        prs,
        "Why We Chose This Challenge",
        [
            _maybe_formalize(args.formalize, args.inspiration or "Housing discovery is fragmented; roommate matching is risky and manual"),
            _maybe_formalize(args.formalize, args.gap or "Gap: Lack of simple, explainable matching and room search for students and professionals"),
        ],
    )
    add_footer(s, footer_text)
    add_icons_for_slide(s, 2, args)

    # Slide 3 — Your understanding about the challenge
    s = add_bullets_slide(
        prs,
        "Understanding the Challenge",
        [
            _maybe_formalize(args.formalize, args.problem or "Align lifestyle, budget, and city preferences reliably"),
            _maybe_formalize(args.formalize, args.audience or "Who faces it: students, early‑career workers, hostel and PG managers"),
            _maybe_formalize(args.formalize, "Why it matters: trust, safety, and faster time to a good match"),
        ],
    )
    add_footer(s, footer_text)
    add_icons_for_slide(s, 3, args)

    # Slide 4 — Your Solution Overview (text bullets or image override)
    solution_image = None
    if getattr(args, "solution_image", ""):
        p = Path(args.solution_image)
        if p.exists():
            solution_image = str(p)
    elif getattr(args, "solution_svg", ""):
        p = Path(args.solution_svg)
        if p.exists():
            out = Path("docs/png/solution_overview.png")
            out.parent.mkdir(parents=True, exist_ok=True)
            if svg_to_png(str(p), str(out)):
                solution_image = str(out)
    # Fallback to defaults if no flags provided
    if not solution_image:
        png_default = Path("docs/png/solution_overview.png")
        mmd_default = Path("docs/solution_overview.mmd")
        if png_default.exists():
            solution_image = str(png_default)
        elif mmd_default.exists():
            png_default.parent.mkdir(parents=True, exist_ok=True)
            if render_mermaid_to_png(str(mmd_default), str(png_default)):
                solution_image = str(png_default)

    if solution_image:
        s = add_image_slide(prs, "Solution Overview", solution_image)
        add_footer(s, footer_text)
        add_icons_for_slide(s, 4, args)
    else:
        s = add_bullets_slide(
            prs,
            "Solution Overview",
            [
                _maybe_formalize(args.formalize, "Agents: Profile Reader, Match Scorer, Red Flag, Wingman, and Room Hunter"),
                _maybe_formalize(args.formalize, "Key flows: /parse, /profiles/{id}/matches, /profiles/{id}/rooms, /rooms/search"),
                _maybe_formalize(args.formalize, "Explainable scores, caution flags, and suggestions; optional degraded mode"),
            ],
        )
        add_footer(s, footer_text)
        add_icons_for_slide(s, 4, args)

    # Slide 5 — Agentic Aspect (text bullets or image override)
    agentic_image = None
    if getattr(args, "agentic_image", ""):
        p = Path(args.agentic_image)
        if p.exists():
            agentic_image = str(p)
    elif getattr(args, "agentic_mmd", ""):
        p = Path(args.agentic_mmd)
        if p.exists():
            out = Path("docs/png/agentic_flow.png")
            out.parent.mkdir(parents=True, exist_ok=True)
            ok = render_mermaid_to_png(str(p), str(out))
            if ok:
                agentic_image = str(out)
    # Fallback to defaults if no flags provided
    if not agentic_image:
        png_default = Path("docs/png/agentic_flow.png")
        mmd_default = Path("docs/agentic_flow.mmd")
        if png_default.exists():
            agentic_image = str(png_default)
        elif mmd_default.exists():
            png_default.parent.mkdir(parents=True, exist_ok=True)
            if render_mermaid_to_png(str(mmd_default), str(png_default)):
                agentic_image = str(png_default)

    if agentic_image:
        s = add_image_slide(prs, "Agentic Aspect", agentic_image)
        add_footer(s, footer_text)
        add_icons_for_slide(s, 5, args)
    else:
        s = add_bullets_slide(
            prs,
            "Agentic Aspect",
            [
                _maybe_formalize(args.formalize, "Sense → parse profile text; Plan → select features and weights"),
                _maybe_formalize(args.formalize, "Act → score, flag, and suggest; Observe → gather feedback from endpoints"),
                _maybe_formalize(args.formalize, "Orchestration: ProfileReader → Scorer → RedFlag → Wingman → RoomHunter"),
            ],
        )
        add_footer(s, footer_text)
        add_icons_for_slide(s, 5, args)

    # Slide 6 — Technical Implementation
    s = add_bullets_slide(
        prs,
        "Technical Implementation",
        [
            _maybe_formalize(args.formalize, args.stack or "Built as a simple web service using reliable Python libraries"),
            _maybe_formalize(args.formalize, args.algorithms or "Compares budgets and daily habits; closely matches room amenities"),
            _maybe_formalize(args.formalize, "Provides endpoints to check status, parse profiles, get matches, and search rooms"),
            _maybe_formalize(args.formalize, args.demo or "Demo: start the app and test the health check and matches routes"),
        ],
    )
    add_footer(s, footer_text)
    add_icons_for_slide(s, 6, args)

    # Slide 7 — Challenges & Accomplishments
    s = add_bullets_slide(
        prs,
        "Challenges & Accomplishments",
        [
            _maybe_formalize(args.formalize, args.challenges or "Parsing noisy text; explainability and safety; performance in low‑compute contexts"),
            _maybe_formalize(args.formalize, args.addressed or "Mitigations: rule‑based normalizers, red‑flag heuristics, and degraded mode"),
            _maybe_formalize(args.formalize, args.accomplishments or "Outcome: end‑to‑end prototype with testable endpoints"),
        ],
    )
    add_footer(s, footer_text)
    add_icons_for_slide(s, 7, args)

    # Optional architecture and sequence image slides
    arch_image = args.arch_image
    # If an .mmd is provided and no image, try rendering to PNG into docs/png/
    if not arch_image and args.arch_mmd:
        png_out = Path("docs/png/architecture_flow.png")
        png_out.parent.mkdir(parents=True, exist_ok=True)
        ok = render_mermaid_to_png(args.arch_mmd, str(png_out))
        if ok:
            arch_image = str(png_out)
    # Fallback to defaults if no flags provided
    if not arch_image:
        png_default = Path("docs/png/architecture_flow.png")
        mmd_default = Path("docs/architecture_flow.mmd")
        if png_default.exists():
            arch_image = str(png_default)
        elif mmd_default.exists():
            png_default.parent.mkdir(parents=True, exist_ok=True)
            if render_mermaid_to_png(str(mmd_default), str(png_default)):
                arch_image = str(png_default)
    if arch_image and Path(arch_image).exists():
        s = add_image_slide(prs, "System Architecture", arch_image)
        add_footer(s, footer_text)
        add_icons_for_slide(s, 8, args)

    seq_image = args.sequence_image
    if seq_image and Path(seq_image).exists():
        s = add_image_slide(prs, "Matching Sequence", seq_image)
        add_footer(s, footer_text)
        add_icons_for_slide(s, 9, args)
    else:
        # Fallback to defaults if no flags provided
        png_default = Path("docs/png/matching_sequence.png")
        mmd_default = Path("docs/matching_sequence.mmd")
        if png_default.exists():
            s = add_image_slide(prs, "Matching Sequence", str(png_default))
            add_footer(s, footer_text)
            add_icons_for_slide(s, 9, args)
        elif mmd_default.exists():
            png_default.parent.mkdir(parents=True, exist_ok=True)
            if render_mermaid_to_png(str(mmd_default), str(png_default)):
                s = add_image_slide(prs, "Matching Sequence", str(png_default))
                add_footer(s, footer_text)
                add_icons_for_slide(s, 9, args)

    # Output
    out_dir = Path(args.outdir or "docs/presentation").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.outfile:
        of_path = Path(args.outfile)
        if not of_path.parent or str(of_path.parent) in {".", ""}:
            outfile = out_dir / of_path.name
        else:
            outfile = of_path.resolve()
    else:
        outfile = out_dir / "Final_Presentation.pptx"
    outfile.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(outfile))
    print(f"Wrote deck: {outfile}")


def parse_args():
    p = argparse.ArgumentParser(description="Generate the final 7-slide presentation deck")
    p.add_argument("--project-name", default="Room Matcher AI")
    p.add_argument("--team", default="RoomMatcher AI")
    p.add_argument("--members", default="Ahmed Mustafa and Maira Anjum")
    p.add_argument("--tagline", default="Minimal multi-agent roommate matcher & room listings search for Pakistan")

    p.add_argument("--inspiration", default="")
    p.add_argument("--gap", default="")
    p.add_argument("--problem", default="")
    p.add_argument("--audience", default="")
    p.add_argument("--stack", default="")
    p.add_argument("--algorithms", default="")
    p.add_argument("--demo", default="")
    p.add_argument("--challenges", default="")
    p.add_argument("--addressed", default="")
    p.add_argument("--accomplishments", default="")

    p.add_argument("--accent", default="#2F5597")
    p.add_argument("--website", default="")
    p.add_argument("--logo", default="")
    p.add_argument("--footer", default="")
    p.add_argument("--background", default="")
    p.add_argument("--formalize", action="store_true")
    # Diagram/image inputs
    p.add_argument("--arch-mmd", default="")
    p.add_argument("--arch-image", default="")
    p.add_argument("--sequence-image", default="")
    # Slide 5 (Agentic) override
    p.add_argument("--agentic-mmd", default="")
    p.add_argument("--agentic-image", default="")
    # Slide 4 override
    p.add_argument("--solution-image", default="")
    p.add_argument("--solution-svg", default="")
    # Icons
    p.add_argument("--icons-global", default="")
    for i in range(1, 10):
        p.add_argument(f"--icons-s{i}", default="")

    p.add_argument("--outdir", default="docs/presentation")
    p.add_argument("--outfile", default="")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    build_deck(args)
