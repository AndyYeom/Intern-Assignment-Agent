"""Render a ResumeSpec to HTML and PDF, following MIT CAPD Resume Template A.

The layout is taken from data/static/MITResumeTemplateA.docx, measured from its
XML rather than eyeballed:

  * Letter, 1-inch margins, Times New Roman
  * name 14pt bold centred, contact line centred with " | " separators
  * section headings 14pt bold, title case, a 0.5pt rule beneath
  * body 11pt; each entry is **Organization**, Location with dates on the right,
    then the role on a plain line, then bullets hanging at 0.25in, text at 0.5in
  * a blank line between entries and before each heading
  * sections: Education, Experience, Activities & Extracurriculars,
    Awards & Accomplishments, Skills & Interests

One addition to the template: a Projects section, styled like Experience. The
resumes are for technical internships, and their projects are exactly what the
evidence agent verifies against GitHub.

Template A has no photo. `photo: true` in a spec still places the placeholder
beside the name, but it is off by default.
"""
from __future__ import annotations

import base64
import html
import io
import os
import sys
from dataclasses import dataclass
from functools import lru_cache

from generator.config import DATA
from generator.resume.schema import Entry, ResumeSpec

PHOTO_PATH = DATA / "static" / "image.png"

# The photo box is 78px wide. 160px is ~2x that, so it stays sharp when printed
# or zoomed; the 350px source was ~12 KB of a ~36 KB PDF for no visible gain.
PHOTO_PX = 160
PHOTO_JPEG_QUALITY = 72

# WeasyPrint needs to find homebrew's pango/cairo on macOS.
if sys.platform == "darwin":
    _existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    if "/opt/homebrew/lib" not in _existing:
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(
            p for p in ["/opt/homebrew/lib", "/usr/local/lib", _existing] if p
        )

@dataclass(frozen=True)
class Layout:
    """One step of the one-page fit. Every step stays within MIT CAPD guidance:
    10-12pt body text and 0.5-1in margins."""

    name: str
    body_pt: float
    heading_pt: float
    margin_in: float
    gap_pt: float          # blank line between entries and before headings
    line_height: float


# Tried in order; the first that fits on one page is used. Step 0 is MIT Template A
# exactly, so a resume within the prompt's budget always looks like the template.
LAYOUTS: tuple[Layout, ...] = (
    Layout("template-a", 11.0, 14.0, 1.00, 12.65, 1.15),
    Layout("margins-075", 11.0, 14.0, 0.75, 10.0, 1.12),
    Layout("compact", 10.5, 13.0, 0.75, 8.5, 1.10),
    Layout("tight", 10.5, 12.5, 0.60, 7.0, 1.08),
    Layout("minimum", 10.0, 12.0, 0.50, 6.0, 1.05),
)
TEMPLATE_A = LAYOUTS[0]


def css(layout: Layout = TEMPLATE_A) -> str:
    gap = layout.gap_pt
    return f"""
@page {{ size: Letter; margin: {layout.margin_in}in; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: "Times New Roman", Times, serif; font-size: {layout.body_pt}pt;
       line-height: {layout.line_height}; color: #000; }}
header {{ text-align: center; }}
header.with-photo {{ display: flex; align-items: center; gap: 14px; text-align: left; }}
header.with-photo .identity {{ flex: 1; text-align: center; }}
.photo {{ width: 72px; height: 72px; object-fit: cover; border: 0.5pt solid #444; }}
h1 {{ font-size: {layout.heading_pt}pt; font-weight: bold; }}
h2 {{ font-size: {layout.heading_pt}pt; font-weight: bold; margin-top: {gap}pt;
     border-bottom: 0.5pt solid #000; padding-bottom: 1pt; }}
.entry + .entry {{ margin-top: {gap}pt; }}
.row {{ display: flex; justify-content: space-between; gap: 12pt; }}
.row .right {{ white-space: nowrap; text-align: right; }}
b {{ font-weight: bold; }}
.nowrap {{ white-space: nowrap; }}
ul {{ list-style: none; }}
li {{ position: relative; padding-left: 0.5in; }}
li::before {{ content: "\\2022"; position: absolute; left: 0.25in; }}
"""


# Kept for callers that only want the template's own stylesheet.
CSS = css(TEMPLATE_A)


def _esc(value: str | None) -> str:
    return html.escape(value or "", quote=True)


@lru_cache(maxsize=1)
def _photo_data_uri() -> str | None:
    """Embed the placeholder photo, downscaled and JPEG-encoded to keep PDFs small."""
    if not PHOTO_PATH.exists():
        return None
    from PIL import Image, ImageChops

    with Image.open(PHOTO_PATH) as source:
        image = source.convert("RGB")
    # A greyscale source needs one channel, not three.
    red, green, blue = image.split()
    if not ImageChops.difference(red, green).getbbox() and \
            not ImageChops.difference(green, blue).getbbox():
        image = image.convert("L")
    image.thumbnail((PHOTO_PX, PHOTO_PX), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=PHOTO_JPEG_QUALITY, optimize=True)
    return f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def _dates(entry: Entry) -> str:
    if entry.start and entry.end:
        return f"{_esc(entry.start)} &ndash; {_esc(entry.end)}"
    return _esc(entry.start or entry.end)


def _row(left: str, right: str = "") -> str:
    return f'<div class="row"><div class="left">{left}</div><div class="right">{right}</div></div>'


def _bullets(items: list[str]) -> str:
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{_esc(item)}</li>" for item in items) + "</ul>"


def _lead(bold: str | None, rest: str | None) -> str:
    """ "**Bold**, rest" - the template's first line of every entry."""
    parts = []
    if bold:
        parts.append(f"<b>{_esc(bold)}</b>")
    if rest and rest != bold:
        parts.append(_esc(rest))
    return ", ".join(parts)


def _entry_html(entry: Entry, *, kind: str) -> str:
    """One dated block in Template A's shape.

    `entry.link` is deliberately never rendered. A project link is the real
    person's repo URL, which carries their real username, and printing it on a
    resume with an invented name would tie that invented identity to a real
    account. The link stays in the spec; the evidence agent joins a resume to
    its profile through data/applicants.csv, not through the PDF.
    """
    if kind == "project":
        # **Project Name**, Personal Project      dates
        # Python, FastAPI, PostgreSQL
        lines = [_row(_lead(entry.title, entry.organization), _dates(entry))]
        if entry.tech:
            lines.append(_row(_esc(", ".join(entry.tech))))
    elif kind == "activity":
        # **Activity**, Role      dates
        lines = [_row(_lead(entry.organization, entry.title), _dates(entry))]
    elif kind == "award":
        # Award      date - one date, never a range: `end` defaults to "Present",
        # which would turn "Mar 2026" into "Mar 2026 - Present".
        date = entry.start or (entry.end if entry.end != "Present" else "")
        lines = [_row(_esc(entry.title), _esc(date))]
    else:
        # **Organization**, Location      dates
        # Title
        lines = [_row(_lead(entry.organization, entry.location), _dates(entry))]
        if entry.title:
            lines.append(_row(_esc(entry.title)))
    return '<div class="entry">' + "".join(lines) + _bullets(entry.bullets) + "</div>"


def _education_html(spec: ResumeSpec) -> str:
    education = spec.education
    degree = education.degree + (f" in {education.major}" if education.major else "")
    if education.minor:
        degree += f"; Minor in {education.minor}"
    lines = [
        _row(_lead(education.school, education.location), _esc(education.graduation)),
        _row(_esc(degree), f"GPA: {_esc(education.gpa)}" if education.gpa else ""),
    ]
    if education.coursework:
        lines.append(_row(f"Coursework: {_esc(', '.join(education.coursework))}"))
    return '<div class="entry">' + "".join(lines) + "</div>"


def _awards_html(spec: ResumeSpec) -> str:
    blocks = [_entry_html(award, kind="award") for award in spec.awards]
    blocks += [f'<div class="entry">{_row(_esc(honor))}</div>' for honor in spec.education.honors]
    return "".join(blocks)


def _skills_html(skills: dict[str, list[str]]) -> str:
    return "".join(
        _row(f"<b>{_esc(category)}:</b> {_esc(', '.join(items))}")
        for category, items in skills.items() if items
    )


SECTION_TITLES = {
    "education": "Education",
    "experience": "Experience",
    "projects": "Projects",
    "leadership": "Activities &amp; Extracurriculars",
    "awards": "Awards &amp; Accomplishments",
    "skills": "Skills &amp; Interests",
}


def to_html(spec: ResumeSpec, layout: Layout = TEMPLATE_A) -> str:
    contact = [spec.location, spec.phone, spec.email, spec.linkedin, spec.github_url,
               spec.portfolio]
    # Each item is unbreakable, so a long line wraps at " | ", never mid-URL.
    contact_line = " | ".join(f'<span class="nowrap">{_esc(c)}</span>' for c in contact if c)
    identity = (f'<div class="identity"><h1>{_esc(spec.full_name)}</h1>'
                f"<div>{contact_line}</div></div>")
    photo_uri = _photo_data_uri() if spec.photo else None
    if photo_uri:
        header = (f'<header class="with-photo"><img class="photo" src="{photo_uri}" alt="" />'
                  f"{identity}</header>")
    else:
        header = f"<header>{identity}</header>"

    content = {
        "education": _education_html(spec),
        "experience": "".join(_entry_html(e, kind="experience") for e in spec.experience),
        "projects": "".join(_entry_html(e, kind="project") for e in spec.projects),
        "leadership": "".join(_entry_html(e, kind="activity") for e in spec.leadership),
        "awards": _awards_html(spec),
        "skills": _skills_html(spec.skills),
    }
    # Section order depends on career stage: a student leads with education and
    # projects, someone changing field leads with the work they have already done.
    sections = [header]
    if spec.objective:
        sections.append(f"<h2>Objective</h2>{_row(_esc(spec.objective))}")
    for name in spec.sections:
        if content.get(name):
            sections.append(f"<h2>{SECTION_TITLES[name]}</h2>{content[name]}")

    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{_esc(spec.full_name)} &mdash; Resume</title>"
        # The pair key, in the PDF's own metadata (Keywords): a copied file still
        # identifies its applicant. Never the login - PDFs get shared.
        f"<meta name='keywords' content='{_esc(spec.applicant_id)}'>"
        "<meta name='generator' content='intern-assignment-agent generator'>"
        f"<style>{css(layout)}</style></head><body>{''.join(sections)}</body></html>"
    )


def _stem(spec: ResumeSpec) -> str:
    """Rendered files are named by applicant ID: two invented "Ada Okonkwo"s cannot
    overwrite each other, and the name reveals nothing."""
    return spec.applicant_id or spec.slug


def page_count(spec: ResumeSpec, layout: Layout = TEMPLATE_A) -> int:
    from weasyprint import HTML

    return len(HTML(string=to_html(spec, layout), base_url=str(DATA)).render().pages)


def fitted_layout(spec: ResumeSpec) -> Layout | None:
    """The first layout, from Template A tightening towards the minimum, that keeps
    the resume on one page; None if even the minimum overflows."""
    for layout in LAYOUTS:
        if page_count(spec, layout) <= 1:
            return layout
    return None


def render_pdf(spec: ResumeSpec, layout: Layout) -> bytes | None:
    """PDF bytes in the given layout, or None if WeasyPrint's libraries are missing.

    Deliberately returns bytes rather than writing a file: generate.publish is the
    only code that writes resume PDFs, so none can exist unpaired in applicants.csv,
    and none can be written without first being fitted to one page.
    """
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        print(f"  ! PDF unavailable ({exc})")
        return None
    document = HTML(string=to_html(spec, layout), base_url=str(DATA)).render()
    if len(document.pages) > 1:
        raise ValueError(f"{spec.applicant_id}: {len(document.pages)} pages in layout "
                         f"{layout.name}; refusing to write a multi-page resume")
    return document.write_pdf()


def pdf_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True
