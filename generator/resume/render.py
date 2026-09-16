"""Render a ResumeSpec to HTML and PDF in the MIT CAPD resume format.

Format rules followed (capd.mit.edu/resources/resume):
  * one page, name centred at the top with a single contact line beneath
  * sections in order: Education, Experience, Projects, Leadership, Skills
  * organisation in bold, role in italic, dates right-aligned on the same line
  * bullets are single-line where possible and start with an action verb
  * serif face, conservative spacing, no colour

The photo is not part of the MIT convention (US resumes omit them); it is
supported because the assignment asks for it, and can be turned off per resume
with `photo: false`.
"""
from __future__ import annotations

import base64
import html
import os
import sys
from pathlib import Path

from generator.config import DATA
from generator.resume.schema import Entry, ResumeSpec

PHOTO_PATH = DATA / "static" / "image.png"

# WeasyPrint needs to find homebrew's pango/cairo on macOS.
if sys.platform == "darwin":
    _existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    if "/opt/homebrew/lib" not in _existing:
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(
            p for p in ["/opt/homebrew/lib", "/usr/local/lib", _existing] if p
        )

CSS = """
@page { size: Letter; margin: 0.5in 0.6in; }
* { box-sizing: border-box; }
body {
  font-family: "Times New Roman", Times, Georgia, serif;
  font-size: 10.2pt; line-height: 1.28; color: #000; margin: 0;
}
header { display: flex; align-items: center; gap: 14px; margin-bottom: 2px; }
header.no-photo { display: block; text-align: center; }
.photo {
  width: 78px; height: 78px; object-fit: cover; flex: 0 0 78px;
  border: 0.5pt solid #444;
}
.identity { flex: 1 1 auto; text-align: center; }
h1 {
  font-size: 17pt; font-weight: bold; letter-spacing: 1.6px;
  margin: 0 0 3px; text-transform: uppercase;
}
.contact { font-size: 9.2pt; }
.contact span:not(:last-child)::after { content: "\\00a0\\00a0\\2022\\00a0\\00a0"; }
h2 {
  font-size: 10.2pt; font-weight: bold; text-transform: uppercase;
  letter-spacing: 1.1px; margin: 9px 0 2px;
  border-bottom: 0.9pt solid #000; padding-bottom: 1px;
}
.row { display: flex; justify-content: space-between; gap: 10px; }
.row .left { flex: 1 1 auto; }
.row .right { flex: 0 0 auto; font-style: italic; white-space: nowrap; }
.org { font-weight: bold; }
.role { font-style: italic; }
ul { margin: 1px 0 4px; padding-left: 16px; }
li { margin: 0 0 1px; }
.entry { margin-bottom: 5px; }
.tech { font-size: 9pt; font-style: italic; }
.skills td { vertical-align: top; padding: 0 0 2px; }
.skills td.cat { font-weight: bold; white-space: nowrap; padding-right: 8px; }
table.skills { width: 100%; border-collapse: collapse; }
.objective { margin: 3px 0 0; text-align: justify; }
a { color: #000; text-decoration: none; }
"""


def _esc(value: str | None) -> str:
    return html.escape(value or "", quote=True)


def _photo_data_uri() -> str | None:
    if not PHOTO_PATH.exists():
        return None
    encoded = base64.b64encode(PHOTO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _dates(entry: Entry) -> str:
    if entry.start and entry.end:
        return f"{_esc(entry.start)} &ndash; {_esc(entry.end)}"
    return _esc(entry.start or entry.end)


def _entry_html(entry: Entry, *, show_link: bool = False, title_first: bool = False) -> str:
    # Experience leads with the employer; a project leads with its own name.
    primary = entry.title if title_first else entry.organization
    secondary = entry.organization if title_first else entry.title

    left_bits = []
    if primary:
        left_bits.append(f'<span class="org">{_esc(primary)}</span>')
    if secondary and secondary != primary:
        left_bits.append(f'<span class="role">{_esc(secondary)}</span>')
    left = ", ".join(left_bits)

    right_bits = []
    if entry.location:
        right_bits.append(_esc(entry.location))
    dates = _dates(entry)
    if dates:
        right_bits.append(dates)
    right = " | ".join(right_bits)

    parts = [(f'<div class="entry"><div class="row"><div class="left">{left}</div>'
              f'<div class="right">{right}</div></div>')]

    if entry.tech:
        parts.append(f'<div class="tech">{_esc(", ".join(entry.tech))}</div>')
    if entry.bullets:
        items = "".join(f"<li>{_esc(b)}</li>" for b in entry.bullets)
        parts.append(f"<ul>{items}</ul>")
    if show_link and entry.link:
        parts.append(f'<div class="tech">{_esc(entry.link)}</div>')
    parts.append("</div>")
    return "".join(parts)


def _education_html(spec: ResumeSpec) -> str:
    education = spec.education
    degree_bits = [education.degree]
    if education.major:
        degree_bits.append(f"in {education.major}")
    degree = " ".join(b for b in degree_bits if b)

    right = " | ".join(b for b in [_esc(education.location), _esc(education.graduation)] if b)
    parts = [('<div class="entry"><div class="row">'
              f'<div class="left"><span class="org">{_esc(education.school)}</span></div>'
              f'<div class="right">{right}</div></div>')]

    line = f'<div class="role">{_esc(degree)}'
    if education.minor:
        line += f"; Minor in {_esc(education.minor)}"
    if education.gpa:
        line += f" &mdash; GPA: {_esc(education.gpa)}"
    parts.append(line + "</div>")

    if education.honors:
        parts.append(f"<div>{_esc('; '.join(education.honors))}</div>")
    if education.coursework:
        parts.append("<div><b>Relevant Coursework:</b> "
                     f"{_esc(', '.join(education.coursework))}</div>")
    parts.append("</div>")
    return "".join(parts)


def _skills_html(skills: dict[str, list[str]]) -> str:
    rows = "".join(
        f'<tr><td class="cat">{_esc(category)}:</td><td>{_esc(", ".join(items))}</td></tr>'
        for category, items in skills.items() if items
    )
    return f'<table class="skills">{rows}</table>'


def to_html(spec: ResumeSpec) -> str:
    contact = [
        _esc(spec.location), _esc(spec.email), _esc(spec.phone),
        _esc(spec.linkedin), _esc(spec.github_url), _esc(spec.portfolio),
    ]
    contact_html = "".join(f"<span>{c}</span>" for c in contact if c)

    photo_uri = _photo_data_uri() if spec.photo else None
    identity = (f'<div class="identity"><h1>{_esc(spec.full_name)}</h1>'
                f'<div class="contact">{contact_html}</div></div>')
    if photo_uri:
        header = f'<header><img class="photo" src="{photo_uri}" alt="" />{identity}</header>'
    else:
        header = f'<header class="no-photo">{identity}</header>'

    sections: list[str] = [header]

    if spec.objective:
        sections.append(f'<h2>Objective</h2><div class="objective">{_esc(spec.objective)}</div>')

    # Section order depends on career stage: a student leads with education and
    # projects, someone changing field leads with the work they have already done.
    builders = {
        "education": lambda: "<h2>Education</h2>" + _education_html(spec),
        "experience": lambda: ("<h2>Experience</h2>" +
                               "".join(_entry_html(e) for e in spec.experience))
        if spec.experience else "",
        "projects": lambda: ("<h2>Projects</h2>" +
                             "".join(_entry_html(e, show_link=True, title_first=True)
                                     for e in spec.projects))
        if spec.projects else "",
        "leadership": lambda: ("<h2>Leadership &amp; Activities</h2>" +
                               "".join(_entry_html(e) for e in spec.leadership))
        if spec.leadership else "",
        "skills": lambda: ("<h2>Technical Skills</h2>" + _skills_html(spec.skills))
        if spec.skills else "",
    }
    for name in spec.sections:
        block = builders[name]()
        if block:
            sections.append(block)

    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{_esc(spec.full_name)} &mdash; Resume</title>"
        f"<style>{CSS}</style></head><body>{''.join(sections)}</body></html>"
    )


def write_html(spec: ResumeSpec, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{spec.slug}.html"
    path.write_text(to_html(spec), encoding="utf-8")
    return path


def write_pdf(spec: ResumeSpec, out_dir: Path) -> Path | None:
    """Render to PDF. Returns None if WeasyPrint's system libraries are missing."""
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        print(f"  ! PDF unavailable ({exc}). HTML was still written.")
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{spec.slug}.pdf"
    HTML(string=to_html(spec), base_url=str(DATA)).write_pdf(str(path))
    return path


def pdf_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True
