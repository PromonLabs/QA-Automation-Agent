"""
PDF Report Generator — clean invoice style.
Simple centred layout with final screenshot, no log tables.

Requires: reportlab (pip install reportlab)
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.models.schemas import ExecutionResult, ExecutionStatus


# ── Try importing reportlab; provide graceful fallback ───────────────────────
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Image
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    _REPORTLAB_OK = True
except ImportError:
    _REPORTLAB_OK = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_dt(iso_str: Optional[str]) -> str:
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d  %H:%M:%S UTC")
    except Exception:
        return iso_str


def _duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s" if m else f"{s}s"


def _status_label(status: ExecutionStatus) -> str:
    return {
        ExecutionStatus.SUCCESS:   "PASS",
        ExecutionStatus.FAILED:    "FAIL",
        ExecutionStatus.CANCELLED: "CANCELLED",
        ExecutionStatus.RUNNING:   "RUNNING",
        ExecutionStatus.PENDING:   "PENDING",
    }.get(status, str(status).upper())


def _find_final_screenshot(result: ExecutionResult) -> Optional[Path]:
    """
    Return the Path of the final screenshot, or None if not found.
    Looks for a filename containing 'final' first; falls back to the last screenshot.
    """
    if not result.screenshots:
        return None

    try:
        from app.core.config import settings
        shot_dir = settings.SCREENSHOTS_DIR / result.id

        for name in reversed(result.screenshots):
            if "final" in name.lower():
                p = shot_dir / name
                if p.exists():
                    return p

        for name in reversed(result.screenshots):
            p = shot_dir / name
            if p.exists():
                return p
    except Exception:
        pass

    return None


def _find_named_screenshot(result: ExecutionResult, filename: str) -> Optional[Path]:
    """Return the Path of a screenshot saved with a specific filename."""
    try:
        from app.core.config import settings
        shot_dir = settings.SCREENSHOTS_DIR / result.id
        # Direct filesystem check — works even if not in the screenshots list
        p = shot_dir / filename
        if p.exists():
            return p
        # Also try case-insensitive match in the list
        for name in result.screenshots:
            if name.lower() == filename.lower():
                p = shot_dir / name
                if p.exists():
                    return p
    except Exception:
        pass
    return None


def _add_screenshot_to_story(story, shot_path: Path, label: str, content_w, gap_fn, hr_fn, label_style) -> None:
    """Add a labelled screenshot block to the story."""
    try:
        try:
            from PIL import Image as PILImage
            with PILImage.open(shot_path) as img:
                img_w, img_h = img.size
            max_w  = content_w
            max_h  = 12 * cm
            scale  = min(max_w / img_w, max_h / img_h)
            draw_w = img_w * scale
            draw_h = img_h * scale
            story.append(Paragraph(label, label_style))
            story.append(Image(str(shot_path), width=draw_w, height=draw_h))
        except ImportError:
            img_obj = Image(str(shot_path), width=content_w)
            img_obj.hAlign = "CENTER"
            story.append(Paragraph(label, label_style))
            story.append(img_obj)
        story.append(gap_fn(12))
    except Exception:
        pass


# ── Public entry point ────────────────────────────────────────────────────────

def generate_pdf(result: ExecutionResult, output_path: Path) -> bool:
    """
    Generate a simple invoice-style PDF at output_path.
    Returns True on success, False if reportlab is not installed.
    """
    if not _REPORTLAB_OK:
        _write_text_report(result, output_path.with_suffix(".txt"))
        return False

    _write_pdf(result, output_path)
    return True


# ── PDF renderer ──────────────────────────────────────────────────────────────

def _write_pdf(result: ExecutionResult, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    H_MARGIN = 1.5 * cm
    V_MARGIN = 1.2 * cm

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=H_MARGIN, leftMargin=H_MARGIN,
        topMargin=V_MARGIN,   bottomMargin=V_MARGIN,
        title=f"Execution Report — {result.flow_name}",
        author="QA Automation Platform",
    )

    content_w = A4[0] - 2 * H_MARGIN   # usable width

    BLACK      = colors.black
    DARK_GREY  = colors.HexColor("#333333")
    MID_GREY   = colors.HexColor("#999999")
    LIGHT_LINE = colors.HexColor("#DDDDDD")

    def _style(name, **kw):
        base = getSampleStyleSheet()["Normal"]
        return ParagraphStyle(name, parent=base, **kw)

    s_header  = _style("Hdr",  fontSize=8,  fontName="Helvetica",      textColor=MID_GREY,  alignment=TA_CENTER)
    s_title   = _style("Ttl",  fontSize=18, fontName="Helvetica-Bold",  textColor=BLACK,     alignment=TA_CENTER)
    s_time    = _style("Tm",   fontSize=10, fontName="Helvetica",       textColor=MID_GREY,  alignment=TA_CENTER)
    s_steps   = _style("Stp",  fontSize=10, fontName="Helvetica",       textColor=DARK_GREY, alignment=TA_CENTER)
    s_lbl     = _style("Lbl",  fontSize=7,  fontName="Helvetica",       textColor=MID_GREY,  alignment=TA_CENTER)
    s_shot_hd = _style("SHd",  fontSize=12, fontName="Helvetica-Bold",  textColor=DARK_GREY, alignment=TA_CENTER, spaceAfter=4)
    s_summary = _style("Sum",  fontSize=10, fontName="Helvetica",       textColor=DARK_GREY, alignment=TA_CENTER, leading=15)
    s_footer  = _style("Ftr",  fontSize=6,  fontName="Helvetica",       textColor=MID_GREY,  alignment=TA_CENTER)

    def HR(thick=0.5, colour=LIGHT_LINE, space_before=0, space_after=4):
        return HRFlowable(width="100%", thickness=thick, color=colour,
                          spaceBefore=space_before, spaceAfter=space_after)
    def gap(h=6):
        return Spacer(1, h)

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph("EXECUTION REPORT", s_header))
    story.append(gap(4))
    story.append(HR(thick=1.2, colour=BLACK, space_after=8))

    story.append(Paragraph(result.flow_name.strip(), s_title))
    story.append(gap(8))
    story.append(HR(space_after=6))

    is_pass      = result.status.value == "success"
    status_color = colors.HexColor("#1a7a3c") if is_pass else colors.HexColor("#b91c1c")
    s_status     = _style("Stat", fontSize=16, fontName="Helvetica-Bold",
                          textColor=status_color, alignment=TA_CENTER)
    story.append(Paragraph(_status_label(result.status), s_status))
    story.append(gap(4))
    story.append(Paragraph(_duration(result.duration_seconds), s_time))
    story.append(gap(6))

    steps_done  = result.steps_completed or 0
    steps_total = result.steps_total or 0
    story.append(Paragraph(f"{steps_done} of {steps_total} steps completed", s_steps))
    story.append(gap(8))
    story.append(HR(space_after=8))

    # ── Detect flow type and pick screenshots accordingly ────────────────────
    flow_name_lo = (result.flow_name or "").lower()
    is_extra_data = "extra" in flow_name_lo or "data" in flow_name_lo

    def _add_shot(path, label, max_h=6 * cm):
        story.append(HR(thick=0.8, colour=DARK_GREY, space_before=4, space_after=4))
        story.append(Paragraph(label, s_shot_hd))
        story.append(HR(thick=0.5, colour=LIGHT_LINE, space_after=4))
        try:
            try:
                from PIL import Image as PILImage
                with PILImage.open(path) as im:
                    w, h = im.size
                scale = min(content_w / w, max_h / h)
                story.append(Image(str(path), width=w * scale, height=h * scale))
            except ImportError:
                story.append(Image(str(path), width=content_w))
        except Exception:
            story.append(Paragraph("(screenshot unavailable)", s_lbl))
        story.append(gap(4))

    if is_extra_data:
        # Extra Data Add: 4 screenshots
        # 1. Before add  → search-result-before.png
        # 2. Payment      → receipt.png
        # 3. Ops COMPLETED → operations-page.png  (captured after refresh_until COMPLETED)
        # 4. After add    → search-result-after.png
        shots = [
            (_find_named_screenshot(result, "search-result-before.png"), "Before Extra Data Add"),
            (_find_named_screenshot(result, "receipt.png"),               "Payment Receipt"),
            (_find_named_screenshot(result, "operations-page.png"),       "Operations Page — COMPLETED"),
            (_find_named_screenshot(result, "search-result-after.png"),   "After Data Add"),
        ]
    else:
        # TopUp Talk: 3 screenshots
        shots = [
            (_find_named_screenshot(result, "search-result.png"),   "Balance Before Top-Up"),
            (_find_named_screenshot(result, "receipt.png"),          "Payment Receipt"),
            (_find_named_screenshot(result, "updated-balance.png"),  "Balance After Top-Up"),
        ]

    if any(p for p, _ in shots):
        for path, label in shots:
            if path:
                _add_shot(path, label)
        story.append(HR(space_after=6))

    # ── SS screenshots — included in every flow that has them ────────────────
    # Any "SS" step in the flow saves a ss_NNN.png; collect and add them all.
    try:
        from app.core.config import settings as _s
        ss_dir = _s.SCREENSHOTS_DIR / result.id
        ss_files = sorted(ss_dir.glob("ss_*.png")) if ss_dir.exists() else []
        if ss_files:
            story.append(HR(thick=0.8, colour=DARK_GREY, space_before=4, space_after=4))
            story.append(Paragraph("Screenshots", s_shot_hd))
            story.append(HR(thick=0.5, colour=LIGHT_LINE, space_after=4))
            for i, ss_path in enumerate(ss_files, 1):
                _add_shot(ss_path, f"Screenshot {i}")
            story.append(HR(space_after=6))
    except Exception:
        pass

    # ── Summary note ─────────────────────────────────────────────────────────
    summary_text = result.result_summary or result.error or ""
    if summary_text:
        story.append(Paragraph(summary_text[:400], s_summary))
        story.append(gap(6))
        story.append(HR(space_after=4))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(gap(4))
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story.append(Paragraph(f"Generated  {generated}", s_footer))

    doc.build(story)


# ── Plain-text fallback (when reportlab is not installed) ─────────────────────

def _write_text_report(result: ExecutionResult, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    status_label = _status_label(result.status)
    steps_total  = result.steps_total or 0
    steps_done   = result.steps_completed or 0
    pct          = int(steps_done / steps_total * 100) if steps_total else 0
    sep = "─" * 52
    lines = [
        "",
        "      EXECUTION REPORT",
        sep,
        f"  {result.flow_name}",
        "",
        f"  {status_label}          {_duration(result.duration_seconds)}",
        "",
        sep,
        f"  Flow ID      {result.flow_id[:36]}",
        f"  Started      {_fmt_dt(result.started_at)}",
        f"  Finished     {_fmt_dt(result.finished_at)}",
        f"  Steps        {steps_done}/{steps_total}  ({pct}%)",
        f"  Exec ID      {result.id[:36]}",
        sep,
    ]
    if result.result_summary:
        lines.append(f"  {result.result_summary}")
    if result.error:
        lines.append(f"  ERROR: {result.error[:200]}")
    lines += [sep, ""]
    output_path.write_text("\n".join(lines), encoding="utf-8")
