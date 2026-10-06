"""Rendering + placeholder validation.

The TEMPLATE decides the engine and the output:
  * .html / .md  -> Jinja2, and WeasyPrint to PDF when out_path ends in .pdf
  * .docx        -> docxtpl (DOCX; PDF via a lazy converter when out_path is .pdf)

BEFORE rendering, validate_template() introspects the template's top-level
placeholders and fails loudly if any references a field ReportModel does not have.
All of jinja2/weasyprint/docxtpl are lazy-imported inside the functions that use
them, so importing this module (and the structural path) needs none of them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Type

from pydantic import BaseModel

from hexharness.reporting.model import ReportModel


def _ext(template_path: str | Path) -> str:
    # ".html.j2" / ".md.j2" collapse to their real format; ".docx" stays.
    suffixes = [s.lower() for s in Path(template_path).suffixes]
    suffixes = [s for s in suffixes if s not in (".j2", ".jinja", ".jinja2", ".tmpl")]
    return suffixes[-1] if suffixes else ""


def introspect_placeholders(template_path: str | Path) -> set[str]:
    """Top-level variable names a template references (loop vars excluded)."""
    ext = _ext(template_path)
    if ext == ".docx":
        from docxtpl import DocxTemplate  # lazy

        tpl = DocxTemplate(str(template_path))
        return set(tpl.get_undeclared_template_variables())

    # Jinja (.html / .md)
    from jinja2 import Environment, meta  # lazy

    source = Path(template_path).read_text()
    ast = Environment().parse(source)
    return set(meta.find_undeclared_variables(ast))


def validate_template(template_path: str | Path, model: Type[BaseModel] = ReportModel) -> set[str]:
    """Raise if the template references a field the model does not define."""
    placeholders = introspect_placeholders(template_path)
    known = set(model.model_fields)
    unknown = placeholders - known
    if unknown:
        raise ValueError(
            f"Template {Path(template_path).name} references unknown "
            f"ReportModel field(s): {', '.join(sorted(unknown))}. Known fields: "
            f"{', '.join(sorted(known))}"
        )
    return placeholders


def render(model: ReportModel, template_path: str | Path, out_path: str | Path) -> Path:
    """Validate, then render model into out_path. Dispatches by template extension."""
    validate_template(template_path, type(model))
    out_path = Path(out_path)
    ext = _ext(template_path)

    if ext == ".docx":
        return _render_docx(model, template_path, out_path)
    return _render_jinja(model, template_path, out_path)


def _render_jinja(model: ReportModel, template_path: str | Path, out_path: Path) -> Path:
    from jinja2 import Environment, select_autoescape  # lazy

    source = Path(template_path).read_text()
    autoescape = select_autoescape(enabled_extensions=("html",), default=_ext(template_path) == ".html")
    env = Environment(autoescape=autoescape)
    rendered = env.from_string(source).render(**model.model_dump())

    if str(out_path).lower().endswith(".pdf"):
        from weasyprint import HTML  # lazy

        # ponytail: a .md template's output is fed to WeasyPrint as HTML as-is.
        # Add a markdown->HTML step if real .md templates (not the default HTML one) are used.
        HTML(string=rendered).write_pdf(str(out_path))
    else:
        out_path.write_text(rendered)
    return out_path


def _render_docx(model: ReportModel, template_path: str | Path, out_path: Path) -> Path:
    from docxtpl import DocxTemplate  # lazy

    tpl = DocxTemplate(str(template_path))
    tpl.render(model.model_dump())

    if str(out_path).lower().endswith(".pdf"):
        # ponytail: DOCX->PDF needs an external converter (LibreOffice/Word).
        # Render DOCX next to the target and hand off; wire docx2pdf here if needed.
        docx_path = out_path.with_suffix(".docx")
        tpl.save(str(docx_path))
        try:
            from docx2pdf import convert  # lazy, optional
        except ImportError as e:
            raise NotImplementedError(
                f"DOCX rendered to {docx_path}; PDF conversion needs the optional "
                f"'docx2pdf' (or a LibreOffice step)."
            ) from e
        convert(str(docx_path), str(out_path))
    else:
        tpl.save(str(out_path))
    return out_path
