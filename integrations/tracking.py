from __future__ import annotations

import hashlib
from typing import Any


def build_tracking_snippet(config: dict[str, Any], *, fingerprint_salt: str = "") -> str:
    """
    Optional lightweight first-party analytics (POST /collect).
    Config keys:
      - analytics_enabled: bool
    """
    if not bool(config.get("analytics_enabled")):
        return ""
    h = hashlib.sha256((fingerprint_salt or "default").encode()).hexdigest()
    fn = f"_t{h[:7]}"
    # Same payload keys for /collect; only the JS wrapper name changes per site.
    return (
        "<script>\n"
        f"(function(){{function {fn}(ev,props){{try{{"
        "var p={event:ev,ts:Date.now(),path:(location&&location.pathname)||'/',"
        "ref:document.referrer||'',ua:navigator.userAgent||''};"
        "if(props){{for(var k in props){{p[k]=props[k];}}}}"
        "fetch('/collect',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify(p)});"
        f"}}catch(_e){{}}}}"
        f"{fn}('pageview');}})();\n"
        "</script>"
    )
