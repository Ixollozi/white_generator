from __future__ import annotations

from xml.sax.saxutils import escape


def newsroom_policy_html(
    slug: str,
    brand: str,
    city: str,
    country: str,
    *,
    mode: str = "draft",
    language: str = "en",
) -> str:
    """
    Newsroom-specific policies (corrections/ethics/republishing).

    mode:
      - draft: may include internal-review language
      - production: no self-referential/legal-advice disclaimers
    """
    s = (slug or "").strip()
    b = escape(str(brand or "Newsroom"))
    c = escape(str(city or "our area"))
    ct = escape(str(country or ""))
    geo = f"{c} ({ct})".strip(" ()") if ct else c
    mode_n = (mode or "draft").strip().lower()
    if mode_n not in ("draft", "production"):
        mode_n = "draft"
    lang = (language or "en").strip().lower()[:2]

    if s == "corrections-policy":
        if lang == "fr":
            body = (
                f"<p><strong>{b}</strong> publie des mises à jour lorsque les faits changent de manière significative. "
                f"Les corrections visent la visibilité, la précision et l'horodatage pour les lecteurs en <strong>{geo}</strong>.</p>"
                f"<h2>Ce qui constitue une correction</h2>"
                f"<p>Les erreurs matérielles (noms, chiffres, lieux, attribution, chronologie) font l'objet d'une note.</p>"
                f"<h2>Comment nous signalons les mises à jour</h2>"
                f"<p>Nous plaçons une mention près du début du texte lorsque c'est possible, avec la date de la modification.</p>"
                f"<h2>Demander une correction</h2>"
                f"<p>Utilisez la page contact en indiquant l'URL, la phrase concernée et les éléments de preuve.</p>"
            )
            if mode_n == "draft":
                body += "<p><em>Brouillon interne : le placement exact peut varier selon le modèle.</em></p>"
        elif lang == "es":
            body = (
                f"<p><strong>{b}</strong> publica actualizaciones cuando los hechos cambian de forma relevante. "
                f"Las correcciones buscan ser visibles, concretas y fechadas para lectores en <strong>{geo}</strong>.</p>"
                f"<h2>Qué cuenta como corrección</h2>"
                f"<p>Los errores materiales (nombres, cifras, lugares, atribución, plazos) se corrigen con una nota.</p>"
                f"<h2>Cómo etiquetamos las actualizaciones</h2>"
                f"<p>Colocamos un aviso cerca del inicio cuando es viable e incluimos la fecha del cambio.</p>"
                f"<h2>Cómo solicitar una corrección</h2>"
                f"<p>Use la página de contacto con la URL, la frase en cuestión y evidencia de apoyo.</p>"
            )
            if mode_n == "draft":
                body += "<p><em>Borrador interno: la ubicación exacta puede variar según la plantilla.</em></p>"
        else:
            body = (
                f"<p><strong>{b}</strong> publishes updates when facts change materially. "
                f"Corrections aim to be visible, specific, and timestamped for readers in <strong>{geo}</strong>.</p>"
                f"<h2>What counts as a correction</h2>"
                f"<p>Material errors (names, numbers, locations, attribution, timelines) are corrected with a note.</p>"
                f"<h2>How we label updates</h2>"
                f"<p>We place an update note near the top of the story when feasible and include the date/time of the change.</p>"
                f"<h2>How to request a correction</h2>"
                f"<p>Use the contact page and include the URL, the sentence in question, and supporting evidence.</p>"
            )
            if mode_n == "draft":
                body += "<p><em>Internal draft: exact placement and wording may vary by template.</em></p>"
        return body

    if s == "ethics-policy":
        if lang == "fr":
            body = (
                f"<p><strong>{b}</strong> vise un journalisme équitable et sourcé. Cette page résume les principes que nous appliquons.</p>"
                f"<h2>Sources</h2>"
                f"<p>Nous privilégions les documents primaires et les sources citées nommément. Si l'anonymat est nécessaire, nous expliquons le contexte.</p>"
                f"<h2>Conflits d'intérêts</h2>"
                f"<p>L'équipe évite les sujets où des intérêts personnels ou financiers pourraient biaiser le traitement.</p>"
                f"<h2>IA et automatisation</h2>"
                f"<p>Nous ne publions pas de prose automatisée non sourcée comme reportage. Les rédacteurs vérifient affirmations et liens avant publication.</p>"
            )
            if mode_n == "draft":
                body += "<p><em>Brouillon interne : adapter aux exigences locales si nécessaire.</em></p>"
        elif lang == "es":
            body = (
                f"<p><strong>{b}</strong> busca un periodismo justo y con fuentes. Esta página resume los estándares que intentamos seguir.</p>"
                f"<h2>Fuentes</h2>"
                f"<p>Preferimos documentos primarios y fuentes identificadas. Si el anonimato es necesario, explicamos el contexto.</p>"
                f"<h2>Conflictos de interés</h2>"
                f"<p>El equipo evita cubrir temas donde conflictos personales o financieros puedan sesgar el relato.</p>"
                f"<h2>IA y automatización</h2>"
                f"<p>No publicamos prosa automática sin respaldo como reportaje. Los editores verifican afirmaciones y enlaces antes de publicar.</p>"
            )
            if mode_n == "draft":
                body += "<p><em>Borrador interno: adapte a requisitos jurisdiccionales si aplica.</em></p>"
        else:
            body = (
                f"<p><strong>{b}</strong> aims for fair, sourced reporting. This page summarizes the standards we try to follow.</p>"
                f"<h2>Sourcing</h2>"
                f"<p>We prefer primary documents and on-the-record sources. When anonymity is necessary, we explain the context.</p>"
                f"<h2>Conflicts of interest</h2>"
                f"<p>Staff avoid covering topics where personal or financial conflicts could bias reporting.</p>"
                f"<h2>AI and automation</h2>"
                f"<p>We do not publish unsourced automated prose as reporting. Editors verify claims and links before publication.</p>"
            )
            if mode_n == "draft":
                body += "<p><em>Internal draft: adapt to jurisdictional requirements as needed.</em></p>"
        return body

    if s == "republishing-policy":
        if lang == "fr":
            body = (
                f"<p><strong>{b}</strong> encourage les liens et les citations courtes avec attribution.</p>"
                f"<h2>Liens</h2>"
                f"<p>Pointez vers l'URL canonique et conservez le titre et la signature lorsque c'est possible.</p>"
                f"<h2>Citations</h2>"
                f"<p>De courts extraits sont autorisés avec attribution claire. La reproduction intégrale requiert une autorisation écrite.</p>"
                f"<h2>Images et graphiques</h2>"
                f"<p>Ne republiez pas d'images ou de graphiques sans licence explicite ou permission.</p>"
            )
            if mode_n == "draft":
                body += "<p><em>Brouillon interne : mettre à jour les mentions de licence si la syndication change.</em></p>"
        elif lang == "es":
            body = (
                f"<p><strong>{b}</strong> acoge enlaces y citas breves con atribución.</p>"
                f"<h2>Enlaces</h2>"
                f"<p>Enlace a la URL canónica y conserve titular y firma cuando sea posible.</p>"
                f"<h2>Citas</h2>"
                f"<p>Se permiten extractos cortos con atribución clara. La reproducción completa requiere permiso por escrito.</p>"
                f"<h2>Imágenes y gráficos</h2>"
                f"<p>No republique imágenes o gráficos salvo que la licencia lo indique o exista permiso.</p>"
            )
            if mode_n == "draft":
                body += "<p><em>Borrador interno: actualice las líneas de licencia si cambian los términos de sindicación.</em></p>"
        else:
            body = (
                f"<p><strong>{b}</strong> welcomes links and short quotations with attribution.</p>"
                f"<h2>Linking</h2>"
                f"<p>Link to the canonical URL and preserve the headline and byline where possible.</p>"
                f"<h2>Quotations</h2>"
                f"<p>Short excerpts are permitted with clear attribution. Full republication requires written permission.</p>"
                f"<h2>Images and graphics</h2>"
                f"<p>Do not republish images or charts unless the license is explicitly stated or permission is granted.</p>"
            )
            if mode_n == "draft":
                body += "<p><em>Internal draft: update licensing lines when syndication terms change.</em></p>"
        return body

    return f"<p>Policy content for <strong>{escape(s)}</strong> is not available.</p>"

