from __future__ import annotations

import hashlib
from xml.sax.saxutils import escape


_VERTICAL_CLAUSES: dict[str, str] = {
    "medical": "<h2>Health information</h2><p>We handle health-related information in accordance with applicable privacy regulations including HIPAA where required. Patient records are stored in secure, access-controlled systems and are only shared with authorized care providers.</p>",
    "dental": "<h2>Patient records</h2><p>Dental records, treatment plans, and imaging are maintained in compliance with applicable health privacy regulations. We retain records for the period required by state dental board guidelines.</p>",
    "legal": "<h2>Attorney-client privilege</h2><p>Communications between you and our attorneys may be protected by attorney-client privilege. We maintain strict confidentiality protocols for all client matters and do not disclose case information without authorization.</p>",
    "accounting": "<h2>Financial data</h2><p>Financial records, tax documents, and bookkeeping data are handled with strict confidentiality. We maintain encrypted storage and access controls consistent with professional accounting standards.</p>",
    "fitness": "<h2>Health and liability</h2><p>Membership involves physical activity. We collect health questionnaire responses to ensure safe participation. This information is stored securely and shared only with coaching staff as needed for safety.</p>",
    "pest_control": "<h2>Property access</h2><p>Our technicians may require access to interior and exterior areas of your property. We carry liability insurance and background-check all field staff. Treatment records are maintained per regulatory requirements.</p>",
}


def legal_document_html(
    brand: str,
    activity: str,
    document_title: str,
    slug: str,
    *,
    mode: str = "draft",
    vertical_id: str = "",
    language: str = "en",
) -> str:
    """
    Multi-section HTML for policy pages.

    mode:
      - draft: includes internal-review disclaimer language
      - production: avoids self-referential "generated/placeholder" language
    Escapes brand/activity for safe insertion into HTML.
    """
    b = escape(str(brand))
    a = escape(str(activity))
    t = escape(str(document_title))
    slug_l = (slug or "").lower().replace("-", " ")

    mode_n = (mode or "draft").strip().lower()
    if mode_n not in ("draft", "production"):
        mode_n = "draft"

    h = int(hashlib.sha256(f"legal|{brand}|{slug}".encode()).hexdigest(), 16)
    structure_variant = h % 5
    lang = (language or "en").strip().lower()[:2]

    def _pick(pool: tuple[str, ...], salt: int) -> str:
        return pool[(salt // 11) % len(pool)]

    _scope_t = ("Scope", "Who this applies to", "Coverage", "Applicability")
    _collect_t = ("Information practices", "What we collect", "Categories of information", "Data we process")
    _use_t = ("How we use information", "Use of data", "Processing purposes", "Why we process data")
    _rights_t = ("Your choices", "Your rights", "Privacy choices", "Control options")
    _ret_t = ("Retention", "How long we keep data", "Data retention", "Storage periods")
    _upd_t = ("Updates", "Changes to this page", "Revisions", "Policy changes")

    if mode_n == "production":
        if lang == "fr":
            intro = (
                f"<p>Cette page sur <strong>{escape(slug_l)}</strong> décrit comment <strong>{b}</strong> traite "
                f"<strong>{t}</strong> pour les visiteurs intéressés par <strong>{a}</strong>. Pour toute question, "
                f"contactez-nous via notre <a href='contact.php'>page contact</a>.</p>"
            )
        elif lang == "es":
            intro = (
                f"<p>Esta página sobre <strong>{escape(slug_l)}</strong> explica cómo <strong>{b}</strong> aborda "
                f"<strong>{t}</strong> para visitantes interesados en <strong>{a}</strong>. Si tiene preguntas, "
                f"contáctenos desde la <a href='contact.php'>página de contacto</a>.</p>"
            )
        else:
            intro = (
                f"<p>This {escape(slug_l)} explains how <strong>{b}</strong> approaches <strong>{t}</strong> "
                f"for visitors interested in <strong>{a}</strong>. If you have questions about this page, "
                f"contact us using the details on our <a href='contact.php'>contact page</a>.</p>"
            )
    else:
        if lang == "fr":
            intro = (
                f"<p>Chez <strong>{b}</strong>, nous traitons <strong>{t}</strong> avec sérieux dans le cadre de "
                f"<strong>{a}</strong>. Ce document est un brouillon pratique pour relecture interne : il résume "
                f"les catégories d'informations, l'usage prévu et les moyens de contact. "
                f"<em>Remplacez par une version validée avant toute utilisation publique.</em></p>"
            )
        elif lang == "es":
            intro = (
                f"<p>En <strong>{b}</strong> tomamos <strong>{t}</strong> en serio en relación con <strong>{a}</strong>. "
                f"Este documento es un borrador práctico para revisión interna: resume categorías de datos, usos previstos "
                f"y cómo contactarnos. <em>Sustituya por texto aprobado antes de uso público.</em></p>"
            )
        else:
            intro = (
                f"<p>At <strong>{b}</strong>, we take <strong>{t}</strong> seriously in connection with our "
                f"work in <strong>{a}</strong>. This document is a practical draft for reviewers and internal "
                f"stakeholders. It summarizes typical categories of information, how we intend to use data, "
                f"and how visitors can reach us with questions. <em>Replace with counsel-approved language "
                f"before any production or public-facing reliance.</em></p>"
            )

    def _heading(text: str, idx: int) -> str:
        et = escape(text)
        if structure_variant == 1:
            return f"<h2>{idx}. {et}</h2>"
        if structure_variant == 2:
            return f"<h3><strong>{et}</strong></h3>"
        if structure_variant == 3:
            return f'<h2 id="policy-h{idx}">{et}</h2>'
        if structure_variant == 4:
            return f'<h2 class="policy-section">{et}</h2>'
        return f"<h2>{et}</h2>"

    scope = (
        f"{_heading(_pick(_scope_t, h), 1)}"
        f"<p>This policy applies to visitors of our website and anyone who interacts with us online "
        f"regarding offerings related to {a}. It does not govern offline agreements unless expressly "
        f"referenced in a signed contract.</p>"
    )

    collect = (
        f"{_heading(_pick(_collect_t, h + 1), 2)}"
        f"<p>Depending on how you interact with us, we may process contact details you provide "
        f"(such as name, email, and phone), messages you send through forms, and basic technical "
        f"information commonly generated when you browse the site (for example device type, rough "
        f"region, and pages viewed). We avoid collecting sensitive categories unless a specific "
        f"service requires it and you choose to provide them.</p>"
    )

    use = (
        f"{_heading(_pick(_use_t, h + 2), 3)}"
        f"<p>We use submissions to respond to inquiries, schedule consultations where offered, "
        f"improve site content and performance, and meet security obligations. We do not sell personal "
        f"information to third parties.</p>"
    )

    rights = (
        f"{_heading(_pick(_rights_t, h + 3), 4)}"
        f"<p>You may contact us to access, correct, or delete certain personal data where applicable "
        f"law provides such rights. You may also opt out of non-essential communications by using "
        f"unsubscribe links where present or by writing to the contact details published on our "
        f"<a href='contact.php'>contact page</a>.</p>"
    )

    retention = (
        f"{_heading(_pick(_ret_t, h + 4), 5)}"
        f"<p>We retain information only as long as needed for the purposes described or as required "
        f"by law. Backup copies may persist for a limited period consistent with our infrastructure "
        f"practices.</p>"
    )

    updates = (
        f"{_heading(_pick(_upd_t, h + 5), 6)}"
        f"<p>We may revise this {escape(slug_l)} page as practices evolve. Continued use after updates "
        f"means you should review the revised document periodically.</p>"
    )

    vertical_clause = _VERTICAL_CLAUSES.get(vertical_id, "")

    disclaimer = ""
    if mode_n == "draft":
        disclaimer = (
            f"<p><strong>Disclaimer:</strong> This text is generated as a non-binding placeholder to "
            f"support website structure and editorial review. It is not legal advice and must be replaced "
            f"or approved by qualified counsel before publication.</p>"
        )

    order_mode = (h // 5) % 3
    if order_mode == 0:
        body = scope + collect + use + vertical_clause + rights + retention + updates
    elif order_mode == 1:
        body = scope + use + collect + vertical_clause + rights + retention + updates
    else:
        body = collect + scope + use + vertical_clause + rights + retention + updates
    return intro + body + disclaimer


def disclaimer_page_html(brand: str, activity: str, *, mode: str = "draft") -> str:
    b = escape(str(brand))
    mode_n = (mode or "draft").strip().lower()
    if mode_n == "production":
        intro = f"<p>The information provided by <strong>{b}</strong> on this website is for general informational purposes only.</p>"
    else:
        intro = f"<p><strong>{b}</strong> provides this disclaimer as a draft for editorial review in connection with {escape(activity)}.</p>"
    body = (
        f"<h2>No professional advice</h2>"
        f"<p>Nothing on this site constitutes professional, legal, financial, or medical advice. "
        f"Consult appropriate professionals before acting on any information found here.</p>"
        f"<h2>Accuracy</h2>"
        f"<p>While we strive to keep information current and accurate, we make no representations "
        f"or warranties about the completeness, accuracy, or reliability of any content.</p>"
        f"<h2>External links</h2>"
        f"<p>This site may contain links to third-party websites. We do not control or endorse "
        f"those sites and are not responsible for their content or practices.</p>"
        f"<h2>Limitation of liability</h2>"
        f"<p>{b} shall not be liable for any losses or damages arising from the use of this website "
        f"or reliance on information provided herein.</p>"
    )
    return intro + body


def accessibility_page_html(brand: str, *, mode: str = "draft") -> str:
    b = escape(str(brand))
    return (
        f"<h2>Accessibility commitment</h2>"
        f"<p><strong>{b}</strong> is committed to ensuring that our website is accessible to all visitors, "
        f"including those with disabilities. We aim to follow WCAG 2.1 guidelines at the AA level.</p>"
        f"<h2>What we do</h2>"
        f"<ul>"
        f"<li>Semantic HTML structure for screen readers</li>"
        f"<li>Sufficient color contrast ratios</li>"
        f"<li>Keyboard-navigable interactive elements</li>"
        f"<li>Alt text for meaningful images</li>"
        f"<li>Responsive design for various devices and screen sizes</li>"
        f"</ul>"
        f"<h2>Feedback</h2>"
        f"<p>If you experience any difficulty accessing content on this site, please contact us "
        f"through our <a href='contact.php'>contact page</a>. We welcome your feedback and will "
        f"work to address accessibility concerns promptly.</p>"
    )
