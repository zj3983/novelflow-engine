"""Model-specific empirical budgets. Token estimates never replace char gates."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

PROFILE_PATH = Path(__file__).with_name("writer_token_calibration.json")


def calibrated_draft_budget(settings: Any, *, target_chars: dict[str,int],
                            acceptance_chars: dict[str,int], profile_path: Path | None = None) -> dict[str,Any] | None:
    try:
        payload = json.loads((profile_path or PROFILE_PATH).read_text(encoding="utf-8"))
        if payload.get("schema_version") != "writer-token-calibration/v1":
            return None
        provider = str(getattr(settings,"provider_id","") or getattr(settings,"provider",""))
        model, protocol = str(settings.model), str(settings.protocol)
        profile = next(p for p in payload["profiles"] if (p.get("provider"),p.get("model"),p.get("protocol")) == (provider,model,protocol))
        if profile.get("validated") is not True:
            return None  # Never activate a fit whose independent trials failed.
        ratio, scale = float(profile["tokens_per_char"]), float(profile.get("budget_scale",1))
        if not (0.2 <= ratio <= 4 and 0.4 <= scale <= 1.1 and int(profile["sample_count"]) >= 1):
            return None
        maximum = int(acceptance_chars["max"])
        if maximum < 1000:
            return None
        planned = min(int(target_chars["min"]), maximum - 250)
        tokens = max(256, int(math.floor(planned * ratio * scale / 50) * 50))
        return {"tokens":tokens,"planned_chars":planned,"sample_count":int(profile["sample_count"]),
                "tokens_per_char":ratio,"budget_scale":scale,"provider":provider,"model":model,
                "protocol":protocol,"measurement":str(profile.get("measurement") or "provider_output_tokens"),
                "native_limit_supported":bool(profile.get("native_output_limit_supported",not protocol.endswith("_cli")))}
    except (OSError,ValueError,TypeError,KeyError,StopIteration,AttributeError):
        return None
