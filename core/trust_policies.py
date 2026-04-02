from __future__ import annotations

from xml.sax.saxutils import escape


def _jurisdiction_key(country: str) -> str:
    u = (country or "").strip().lower()
    if "canada" in u:
        return "ca"
    if "australia" in u:
        return "au"
    if "ireland" in u or "singapore" in u:
        return "ie_sg"
    return "intl"


def trust_policy_html(
    slug: str,
    brand: str,
    city: str,
    country: str,
    founded_year: str | int | None,
    *,
    mode: str = "draft",
) -> str:
    """Substantive HTML for refund / shipping pages."""
    b = escape(str(brand))
    c = escape(str(city or "your region"))
    ct = escape(str(country or ""))
    fy = escape(str(founded_year or ""))
    mode_n = (mode or "draft").strip().lower()
    if mode_n not in ("draft", "production"):
        mode_n = "draft"
    jk = _jurisdiction_key(str(country or ""))

    if slug == "refund-policy":
        ca_note = ""
        if jk == "ca":
            ca_note = (
                "<p>Canadian customers may have additional rights under provincial consumer protection statutes; "
                "where those rights exceed this policy, they prevail.</p>"
            )
        elif jk == "au":
            ca_note = (
                "<p>Australian Consumer Law may provide remedies that cannot be excluded; nothing here limits "
                "those guarantees where they apply.</p>"
            )
        elif jk == "ie_sg":
            ca_note = (
                "<p>EU and Singapore consumer rules may impose mandatory cooling-off or defect remedies for "
                "distance contracts; this page is additive, not a replacement.</p>"
            )
        window = "30 calendar days" if jk != "au" else "30 calendar days (or longer where ACL requires)"
        tail = (f"<p><em>Operating since {fy} — internal policy draft for reviewers.</em></p>" if fy and mode_n == "draft" else "")
        return (
            f"<p>At <strong>{b}</strong>, we want you to know exactly how returns and refunds work "
            f"before you buy. The terms below apply to qualifying purchases shipped to or fulfilled "
            f"for customers in <strong>{c}</strong> ({ct}). They supplement (and do not replace) any "
            f"stricter rights you may have under local consumer law.</p>"
            f"{ca_note}"
            f"<h2>Eligibility</h2>"
            f"<p>Unused items in original packaging may be returned within <strong>{window}</strong> "
            f"of delivery or pickup, unless an item page states a shorter window for hygiene, digital, "
            f"or custom-made products. Gift cards and perishable goods are generally final sale.</p>"
            f"<h2>How to start a return</h2>"
            f"<p>Contact us through the site form with your order reference and photos if the item "
            f"arrived damaged. We reply within two business days with a return label where applicable "
            f"or instructions for drop-off.</p>"
            f"<h2>Refunds timing</h2>"
            f"<p>Once we receive and inspect the return, approved refunds are issued to the original "
            f"payment method within <strong>5–10 business days</strong>, depending on your bank or card "
            f"network. Partial refunds may apply if an item shows wear beyond normal inspection.</p>"
            f"<h2>Exceptions</h2>"
            f"<p>Services already rendered, final-sale merchandise clearly marked at checkout, and "
            f"corporate or event orders under a signed statement of work follow the contract annexed "
            f"to the invoice instead of this page.</p>"
            + tail
        )

    if slug == "shipping-policy":
        domestic = ""
        if jk == "ca":
            domestic = (
                f"<h2>Canada</h2>"
                f"<p><strong>Standard:</strong> 3–9 business days after dispatch to most urban addresses in "
                f"<strong>{c}</strong>. <strong>Express:</strong> 2–4 business days where carriers publish "
                f"service to your postal code. Remote and northern routes may add several days beyond estimates.</p>"
            )
        elif jk == "au":
            domestic = (
                f"<h2>Australia</h2>"
                f"<p><strong>Standard:</strong> 3–8 business days after dispatch within metro areas near "
                f"<strong>{c}</strong>. <strong>Express:</strong> 1–3 business days where offered. "
                f"WA, NT, and rural drops may exceed published ranges.</p>"
            )
        elif jk == "ie_sg":
            domestic = (
                f"<h2>Domestic & nearby</h2>"
                f"<p><strong>Standard:</strong> 2–6 business days after dispatch for local fulfillment around "
                f"<strong>{c}</strong>. Cross-border EU or regional hops may add customs handling even when "
                f"duties are zero-rated.</p>"
            )
        else:
            domestic = (
                f"<h2>Domestic (primary country)</h2>"
                f"<p><strong>Standard:</strong> 3–7 business days after dispatch. "
                f"<strong>Express:</strong> 1–3 business days where the carrier offers it to your postcode. "
                f"Rates shown at checkout are based on weight and dimensions—not flat marketing numbers.</p>"
            )

        tail = (f"<p><em>In business since {fy} — shipping matrix updated with each rate card change.</em></p>" if fy and mode_n == "draft" else "")
        return (
            f"<p><strong>{b}</strong> ships and schedules fulfillment from our operations in "
            f"<strong>{c}</strong>. Delivery timelines are estimates; weather, carrier capacity, and "
            f"customs (for international orders) can add delay.</p>"
            f"{domestic}"
            f"<h2>Neighbouring regions</h2>"
            f"<p>Where we cross-border ship, duties and taxes may be collected at delivery. We display "
            f"an estimate when checkout can calculate it; otherwise the carrier bills on arrival.</p>"
            f"<h2>Processing time</h2>"
            f"<p>Orders pack within <strong>1–2 business days</strong> except during listed holiday blackouts. "
            f"You receive tracking when the label is created, not when the truck leaves the hub.</p>"
            f"<h2>Failed delivery</h2>"
            f"<p>If a package returns as unclaimed, we can reship after confirming the address and "
            f"charging any carrier return fees spelled out in your order confirmation.</p>"
            + tail
        )

    return f"<p>Policy content for <strong>{escape(slug)}</strong> is not available.</p>"


def service_policy_html(
    slug: str,
    brand: str,
    activity: str,
    city: str,
    country: str,
    founded_year: str | int | None,
    *,
    mode: str = "draft",
) -> str:
    """Service-business variants for refund/shipping slugs."""
    b = escape(str(brand))
    a = escape(str(activity or "our services"))
    c = escape(str(city or "your region"))
    ct = escape(str(country or ""))
    fy = escape(str(founded_year or ""))
    mode_n = (mode or "draft").strip().lower()
    if mode_n not in ("draft", "production"):
        mode_n = "draft"
    geo = f"{c} ({ct})".strip(" ()") if ct else c

    if slug == "refund-policy":
        intro = (
            f"<p>This page describes how <strong>{b}</strong> handles cancellations, rescheduling, and credits "
            f"for work related to <strong>{a}</strong> in <strong>{geo}</strong>.</p>"
            if mode_n == "production"
            else f"<p>This page describes how <strong>{b}</strong> handles cancellations, rescheduling, and credits "
            f"for work related to <strong>{a}</strong> in <strong>{geo}</strong>. It is a practical draft for review, "
            f"not legal advice.</p>"
        )
        tail = (f"<p><em>Operating since {fy} — internal policy draft for reviewers.</em></p>" if fy and mode_n == "draft" else "")
        return (
            intro
            +
            f"<h2>Cancellations</h2>"
            f"<p>If you need to cancel a scheduled visit, contact us as early as possible. Same-day cancellations may "
            f"incur a fee to cover travel time and reserved labor blocks.</p>"
            f"<h2>Rescheduling</h2>"
            f"<p>We’ll offer the next available slot and confirm the updated scope. If access requirements change "
            f"(keys, security desk, parking), we may adjust timing.</p>"
            f"<h2>Credits & billing</h2>"
            f"<p>For prepaid blocks, unused time can be credited to a future visit where feasible. For recurring plans, "
            f"billing terms follow the agreement on your invoice or statement of work.</p>"
            f"<h2>Exceptions</h2>"
            f"<p>Emergency call-outs, remediation work, and special-event coverage may have separate terms due to staffing "
            f"requirements and short notice.</p>"
            + tail
        )

    if slug == "shipping-policy":
        intro = (
            f"<p>This page outlines how <strong>{b}</strong> delivers and schedules services for <strong>{a}</strong> "
            f"in <strong>{geo}</strong>.</p>"
            if mode_n == "production"
            else f"<p>This page outlines how <strong>{b}</strong> delivers and schedules services for <strong>{a}</strong> "
            f"in <strong>{geo}</strong>. It replaces e-commerce shipping language with service-delivery expectations.</p>"
        )
        tail = (f"<p><em>In business since {fy} — service delivery notes reviewed periodically.</em></p>" if fy and mode_n == "draft" else "")
        return (
            intro
            +
            f"<h2>Service windows</h2>"
            f"<p>Standard visits are scheduled within published hours. Arrival windows may vary by route density, access "
            f"constraints, and building rules.</p>"
            f"<h2>Scope confirmation</h2>"
            f"<p>Before the first visit, we confirm surfaces, access, and any restricted areas. If the on-site condition "
            f"differs materially from the described scope, we’ll confirm changes before proceeding.</p>"
            f"<h2>Supplies & materials</h2>"
            f"<p>Unless otherwise agreed, we bring standard supplies. Specialty chemistry for sensitive finishes may be "
            f"specified in writing to avoid damage and residue.</p>"
            f"<h2>Missed access</h2>"
            f"<p>If we cannot access the site at the confirmed time, the visit may be marked missed and rescheduled, with "
            f"any applicable call-out fee disclosed in advance.</p>"
            + tail
        )

    return f"<p>Policy content for <strong>{escape(slug)}</strong> is not available.</p>"
