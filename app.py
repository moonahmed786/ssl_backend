from fastapi import FastAPI, HTTPException, Body, Query
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import json
import time
import math
import re
from collections import Counter
from fastapi.middleware.cors import CORSMiddleware

# === CONFIG - filenames in same folder ===
PROFILES_FILE = "synthetic_roommate_profiles_pakistan_400.json"
LISTINGS_FILE = "housing_listings_pakistan_400.json"

# === LOAD DATA ON STARTUP ===
with open(PROFILES_FILE, "r", encoding="utf-8") as f:
    profiles = json.load(f)

with open(LISTINGS_FILE, "r", encoding="utf-8") as f:
    listings = json.load(f)

profiles_by_id = {p["id"]: p for p in profiles}
listings_by_id = {l["listing_id"]: l for l in listings}

# === Pydantic models (for endpoints) ===
class ParseRequest(BaseModel):
    raw_text: str
    source_id: Optional[str] = None

class MatchRequest(BaseModel):
    profile_a: str
    profile_b: str
    degraded: Optional[bool] = False

class MatchResult(BaseModel):
    candidate_id: str
    score: float
    flags: List[str]
    explanation: Dict[str, Any]
    agent_plan: List[Dict[str, Any]]

class RoomSearchRequest(BaseModel):
    raw_text: Optional[str] = None
    city: Optional[str] = None
    budget_PKR: Optional[int] = None
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    top_n: int = 5

# === UTILITIES & NORMALIZERS ===
def now_ms():
    return int(time.time()*1000)

# Keywords mapping for Urdu/English (extendable)
URDU_KEYWORDS = {
    "clean": ["clean", "neat", "saaf", "safai", "neat", "tidy", "saaf sutra"],
    "messy": ["messy", "untidy", "ganda", "dark", "dirty"],
    "vegetarian": ["veg", "vegetarian", "shakahari", "vegeterian", "sabzi"],
    "non_veg": ["non-veg","non veg","meat","chicken","beef"],
    "smoke": ["smoke", "smokes", "smoker", "cigarette", "cigarettes", "smoking"],
    "no_smoke": ["no smoking","non smoker","no-smoke","non-smoker","no smoking please","no smoking allowed"],
    "party": ["party", "friends", "guests", "hosting", "host", "host often", "hosts friends"],
    "music": ["tabla","drums","music","sitar","guitar","practice"],
    "pets": ["pet","cats","dogs","dog","cat","pets allowed"],
    "no_pets": ["no pet","no pets","pet not allowed","no pets allowed"],
}

# Cleanliness mapping
CLEAN_MAP = {
    "high": 5,
    "medium": 3,
    "low": 1
}

# --- Rule-based Profile Reader Agent ---
def profile_reader_rule(raw_text: str) -> Dict[str, Any]:
    t = raw_text.lower()
    out = {
        "raw_text": raw_text,
        "city": None,
        "budget_PKR": None,
        "budget_min": None,
        "budget_max": None,
        "cleanliness": None,    # 1..5 numeric
        "sleep_schedule": None, # "early", "flexible", "night"
        "study_habits": None,   # "morning","afternoon","night","flexible"
        "noise_tolerance": None,# 1..5
        "smoking": None,        # True/False/None
        "pets": None,           # True/False/None
        "food_pref": None,      # vegetarian/non-veg/none
    }

    # quick city extraction (common cities in dataset)
    cities = ["lahore","karachi","islamabad","rawalpindi","multan","peshawar","faisalabad"]
    for city in cities:
        if city in t:
            out["city"] = city.title()
            break

    # budget extraction patterns: numbers (e.g., 25k, 25000, 25,000)
    m = re.search(r"(\d{1,2}(?:[,\.]\d{3})?)(k|K)?", raw_text)
    if m:
        num_txt = m.group(1).replace(",", "").replace(".", "")
        try:
            val = int(num_txt)
            if m.group(2) and m.group(2).lower() == "k":
                val = val * 1000
            # a common dataset assumption: if value < 1000 and not with 'k', treat as thousands
            if val < 1000:
                val = val * 1000
            out["budget_PKR"] = val
            out["budget_min"] = int(val*0.8)
            out["budget_max"] = int(val*1.2)
        except:
            pass

    # cleanliness detection
    for kw in URDU_KEYWORDS["clean"]:
        if kw in t:
            out["cleanliness"] = 5
            break
    for kw in URDU_KEYWORDS["messy"]:
        if kw in t and out["cleanliness"] is None:
            out["cleanliness"] = 1
            break
    if out["cleanliness"] is None:
        # words like 'average' or missing -> medium
        if "average" in t or "moderate" in t:
            out["cleanliness"] = 3
        else:
            out["cleanliness"] = 3

    # noise tolerance (inferred)
    if any(k in t for k in URDU_KEYWORDS["party"]+URDU_KEYWORDS["music"]):
        out["noise_tolerance"] = 5
    elif "quiet" in t or "silent" in t or "no guests" in t:
        out["noise_tolerance"] = 1
    else:
        out["noise_tolerance"] = 3

    # smoking
    if any(k in t for k in URDU_KEYWORDS["no_smoke"]):
        out["smoking"] = False
    elif any(k in t for k in URDU_KEYWORDS["smoke"]):
        out["smoking"] = True
    else:
        out["smoking"] = None

    # pets
    if any(k in t for k in URDU_KEYWORDS["no_pets"]):
        out["pets"] = False
    elif any(k in t for k in URDU_KEYWORDS["pets"]):
        out["pets"] = True
    else:
        out["pets"] = None

    # food preference
    if any(k in t for k in URDU_KEYWORDS["vegetarian"]):
        out["food_pref"] = "vegetarian"
    elif any(k in t for k in URDU_KEYWORDS["non_veg"]):
        out["food_pref"] = "non-veg"
    else:
        out["food_pref"] = None

    # sleep schedule detection
    # look for times like 10pm, 11pm, 23:00 or words 'night' 'early'
    if re.search(r"\b(?:\d{1,2}\s*(?:pm|am))\b", t) or "night" in t or "late" in t:
        out["sleep_schedule"] = "night"
    elif "early" in t or "morning" in t or "6am" in t or "7am" in t:
        out["sleep_schedule"] = "early"
    else:
        out["sleep_schedule"] = "flexible"

    # study habits
    if "study at night" in t or "studies at night" in t:
        out["study_habits"] = "night"
    elif "morning study" in t or "studies in morning" in t:
        out["study_habits"] = "morning"
    else:
        out["study_habits"] = "flexible"

    return out

# === Match Scorer Agent ===
def budget_interval(budget: Optional[int]):
    if not budget:
        return 0, 1_000_000_000
    low = int(budget * 0.8)
    high = int(budget * 1.2)
    return low, high

def budget_iou(a_low,a_high,b_low,b_high):
    inter_low = max(a_low,b_low)
    inter_high = min(a_high,b_high)
    if inter_high < inter_low:
        return 0.0
    inter = inter_high - inter_low
    union = max(a_high,b_high) - min(a_low,b_low)
    return inter / union if union>0 else 0.0

def sleep_compat(a_sleep, b_sleep):
    # exact match strong, night vs early weak
    if a_sleep == b_sleep:
        return 1.0
    if {a_sleep, b_sleep} == {"night", "early"}:
        return 0.2
    return 0.6

def numeric_similarity(a,b,scale=4):
    return max(0.0, 1 - abs(a-b)/scale)

def match_score(a: Dict, b: Dict, weights=None):
    # weights may be tuned
    if weights is None:
        weights = {"sleep":0.25, "clean":0.25, "noise":0.2, "budget":0.25, "special":0.05}

    s_sleep = sleep_compat(a.get("sleep_schedule"), b.get("sleep_schedule"))
    s_clean = 1 - abs(int(a.get("cleanliness",3)) - int(b.get("cleanliness",3))) / 4.0
    s_noise = 1 - abs(int(a.get("noise_tolerance",3)) - int(b.get("noise_tolerance",3))) / 4.0
    a_low,a_high = budget_interval(a.get("budget_PKR"))
    b_low,b_high = budget_interval(b.get("budget_PKR"))
    s_budget = budget_iou(a_low,a_high,b_low,b_high)
    # special: smoking & pets alignment (1 if same or unknown, 0 if mismatch)
    sm = 1.0
    if (a.get("smoking") is False and b.get("smoking") is True) or (a.get("smoking") is True and b.get("smoking") is False):
        sm = 0.0
    pet = 1.0
    if (a.get("pets") is False and b.get("pets") is True) or (a.get("pets") is True and b.get("pets") is False):
        pet = 0.0
    s_special = (sm + pet) / 2.0

    total = (weights["sleep"]*s_sleep + weights["clean"]*s_clean + weights["noise"]*s_noise + weights["budget"]*s_budget + weights["special"]*s_special)
    return round(float(total), 4), {"components": {"sleep":s_sleep, "clean":s_clean, "noise":s_noise, "budget":s_budget, "special":s_special}}

# === Red Flag Agent ===
NOISY_KEYWORDS = ["friends", "party", "tabla", "drums", "music", "host", "hosts", "host frequent", "guests", "hosting"]

def red_flag_detector(a: Dict, b: Dict) -> List[str]:
    flags = []
    # noise conflict: one low noise tolerance, other mentions noisy keywords in raw text
    if (a.get("noise_tolerance") and int(a.get("noise_tolerance")) <= 2) and any(k in (b.get("raw_text") or "").lower() for k in NOISY_KEYWORDS):
        flags.append("noise_conflict")
    if (b.get("noise_tolerance") and int(b.get("noise_tolerance")) <= 2) and any(k in (a.get("raw_text") or "").lower() for k in NOISY_KEYWORDS):
        if "noise_conflict" not in flags:
            flags.append("noise_conflict")

    # smoking conflict
    if (a.get("smoking") is False and b.get("smoking") is True) or (a.get("smoking") is True and b.get("smoking") is False):
        flags.append("smoking_conflict")

    # pets conflict
    if (a.get("pets") is False and b.get("pets") is True) or (a.get("pets") is True and b.get("pets") is False):
        flags.append("pets_conflict")

    # budget mismatch extreme (no overlap)
    a_low,a_high = budget_interval(a.get("budget_PKR"))
    b_low,b_high = budget_interval(b.get("budget_PKR"))
    if a_high < b_low or b_high < a_low:
        flags.append("budget_mismatch")

    # suspicious content (scam patterns)
    scam_keywords = ["western union", "send money", "bank transfer first", "deposit first", "call to whatsapp only", "agent", "no id", "no documents"]
    if any(k in (a.get("raw_text") or "").lower() for k in scam_keywords) or any(k in (b.get("raw_text") or "").lower() for k in scam_keywords):
        flags.append("suspicious_content")

    return list(dict.fromkeys(flags))  # remove duplicates preserving order

# === Wingman Agent (Explainability + suggestions) ===
def wingman_explain(a: Dict, b: Dict, score: float, components: Dict, flags: List[str]) -> Dict[str, Any]:
    reasons = []
    suggestions = []

    # Reasons based on components
    if score >= 0.8:
        reasons.append("High overall compatibility.")
    elif score >= 0.6:
        reasons.append("Moderate compatibility; some differences can be negotiated.")
    else:
        reasons.append("Low compatibility; notable differences present.")

    # component explanations
    reasons.append(f"Sleep compatibility: {components['sleep']:.2f}. Cleanliness similarity: {components['clean']:.2f}. Noise alignment: {components['noise']:.2f}. Budget overlap: {components['budget']:.2f}.")

    # special flags
    if "noise_conflict" in flags:
        reasons.append("Possible noise conflict detected: one side prefers quiet while the other mentions hosting/ music/ guests.")
        suggestions.append("Agree fixed quiet hours on weekdays; use headphones or schedule practice days.")
    if "smoking_conflict" in flags:
        reasons.append("Smoking disagreement: one is smoker while the other is non-smoker.")
        suggestions.append("Consider designated smoking areas or find a non-smoking match.")
    if "pets_conflict" in flags:
        reasons.append("Pets disagreement: one allows/has pets while the other doesn't.")
        suggestions.append("Discuss pet rules or find pet-friendly housing if both accept.")
    if "budget_mismatch" in flags:
        reasons.append("Budget mismatch: the two profiles' budgets don't overlap.")
        suggestions.append("Consider adjusting expectations or searching for cheaper/closer listings.")

    if "suspicious_content" in flags:
        reasons.append("Warning: suspicious text found; exercise caution and verify identity/listing.")

    # Short summary
    short = []
    if score >= 0.75:
        short.append("Good match")
    elif score >= 0.5:
        short.append("Potential match (some negotiation needed)")
    else:
        short.append("Not recommended")

    return {"short": " / ".join(short), "reasons": reasons, "suggestions": suggestions}

# === Room Hunter Agent ===
def room_hunter_for_pair(a: Dict, b: Dict, top_n=5):
    # city-level filter: prefer city overlap, else return empty
    city = (a.get("city") or "").lower() or (b.get("city") or "").lower()
    if not city:
        return []

    # budget intersection
    a_low,a_high = budget_interval(a.get("budget_PKR"))
    b_low,b_high = budget_interval(b.get("budget_PKR"))
    inter_low = max(a_low,b_low)
    inter_high = min(a_high,b_high)
    if inter_low > inter_high:
        # no intersection -> return empty
        return []

    candidates = []
    for L in listings:
        if L.get("availability","").lower() != "available":
            continue
        if (L.get("city") or "").lower() != city:
            continue
        rent = L.get("monthly_rent_PKR", 0)
        if rent < inter_low or rent > inter_high:
            continue
        # score by closeness to middle of budget and amenity match (simple)
        mid = (inter_low + inter_high) / 2
        rent_score = 1 - abs(rent - mid)/(mid if mid>0 else 1)
        # amenity match: count how many amenities requested by both (no explicit amenity preferences in dataset; prefer more amenities)
        amen_score = min(1.0, len(L.get("amenities", [])) / 6.0)
        final_score = round(0.6*rent_score + 0.4*amen_score, 4)
        candidates.append((final_score, L))
    candidates_sorted = sorted(candidates, key=lambda x: x[0], reverse=True)
    return [ {"listing_id": c[1]["listing_id"], "city": c[1]["city"], "area": c[1]["area"], "monthly_rent_PKR": c[1]["monthly_rent_PKR"], "amenities": c[1].get("amenities", []), "score": c[0]} for c in candidates_sorted[:top_n] ]

# === Agent-Orchestrator wrappers that produce plan trace logs ===
def run_match_pipeline(profile_id: str, candidate_id: str, degraded: bool = False) -> MatchResult:
    start_total = now_ms()
    agent_plan = []
    # fetch
    start = now_ms()
    a = profiles_by_id.get(profile_id)
    b = profiles_by_id.get(candidate_id)
    agent_plan.append({"agent":"Loader", "action":"fetched_profiles", "time_ms": now_ms()-start})

    if a is None or b is None:
        raise ValueError("profile id(s) not found")

    # If profile entries are raw/unstructured (some entries may already be structured), ensure keys exist
    # For safety: if any profile has 'raw_profile_text' use that, else try 'raw_text' or build from fields
    for x in (a,b):
        if "raw_text" not in x and "raw_profile_text" in x:
            x["raw_text"] = x["raw_profile_text"]
        if "raw_text" not in x:
            # synthesize raw_text from available fields if absent
            x["raw_text"] = " ".join(str(x.get(k,"")) for k in ["city","summary","notes","bio"] if k in x)

    # Profile Reader (skip if profile appears structured and normalized)
    start = now_ms()
    # decide if the profile seems unparsed: use presence of 'normalized' marker; otherwise parse raw_text and merge
    a_parsed = profile_reader_rule(a.get("raw_text", "")) if "normalized" not in a else a
    b_parsed = profile_reader_rule(b.get("raw_text", "")) if "normalized" not in b else b
    # merge parsed fields into a copy so we don't overwrite original entries
    merged_a = {**a, **a_parsed}
    merged_b = {**b, **b_parsed}
    agent_plan.append({"agent":"ProfileReader", "action":"parsed", "time_ms": now_ms()-start})

    # Match Scorer
    start = now_ms()
    score, components = match_score(merged_a, merged_b)
    agent_plan.append({"agent":"MatchScorer", "action":"scored", "score": score, "components": components, "time_ms": now_ms()-start})

    # Red Flag Agent
    start = now_ms()
    flags = red_flag_detector(merged_a, merged_b)
    agent_plan.append({"agent":"RedFlagAgent", "action":"detected", "flags": flags, "time_ms": now_ms()-start})

    # Wingman explanation
    start = now_ms()
    explanation = wingman_explain(merged_a, merged_b, score, components, flags)
    agent_plan.append({"agent":"WingmanAgent", "action":"explained", "summary": explanation.get("short"), "time_ms": now_ms()-start})

    # Room Hunter (optional) - only if score is positive and cities known
    start = now_ms()
    rooms = room_hunter_for_pair(merged_a, merged_b, top_n=5)
    agent_plan.append({"agent":"RoomHunter", "action":"searched", "found": len(rooms), "time_ms": now_ms()-start})

    total_time = now_ms() - start_total
    agent_plan.append({"agent":"Controller", "action":"total", "time_ms": total_time})

    # Build MatchResult-like dict
    result = {
        "candidate_id": candidate_id,
        "score": score,
        "flags": flags,
        "explanation": {
            "wingman": explanation,
            "rooms": rooms
        },
        "agent_plan": agent_plan
    }
    return result

# === FastAPI app & endpoints ===
app = FastAPI(title="Room Matcher AI (Minimal Multi-Agent)")

# CORS: allow local frontend origins
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status":"ok", "profiles_loaded": len(profiles), "listings_loaded": len(listings)}

@app.get("/profiles", summary="List available profiles", response_model=List[Dict])
def list_profiles(limit:int = Query(100, description="Max number of profiles to return")):
    return profiles[:limit]

@app.get("/profiles/{profile_id}", summary="Get profile by ID", response_model=Dict)
def get_profile(profile_id: str):
    p = profiles_by_id.get(profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="Profile not found")
    return p

@app.post("/parse", summary="Parse a raw roommate ad into structured profile")
def parse_ad(req: ParseRequest):
    parsed = profile_reader_rule(req.raw_text)
    # attach source_id if provided
    if req.source_id:
        parsed["source_id"] = req.source_id
    parsed["normalized"] = True
    return {"parsed_profile": parsed}

@app.get("/profiles/{profile_id}/matches", summary="Top matches for a profile")
def profile_matches(profile_id: str, top_k: int = 5, degraded: bool = False):
    if profile_id not in profiles_by_id:
        raise HTTPException(status_code=404, detail="Profile not found")
    # compute pairwise scores against dataset
    results = []
    for p in profiles:
        if p["id"] == profile_id:
            continue
        try:
            res = run_match_pipeline(profile_id, p["id"], degraded=degraded)
        except Exception as e:
            continue
        results.append(res)
    # sort by score - penalize certain flags heavily
    def penalized_score(r):
        penalty = 0.0
        if "suspicious_content" in r["flags"]: penalty += 0.5
        if "budget_mismatch" in r["flags"]: penalty += 0.2
        return r["score"] - penalty
    results_sorted = sorted(results, key=lambda r: penalized_score(r), reverse=True)
    # top_k results
    return results_sorted[:top_k]

@app.get("/profiles/{profile_id}/rooms", summary="Room suggestions for a single profile (based on profile budget & city)")
def profile_rooms(profile_id: str, top_n: int = 5):
    if profile_id not in profiles_by_id:
        raise HTTPException(status_code=404, detail="Profile not found")
    p = profiles_by_id[profile_id]
    # if p is unnormalized, parse first
    parsed = profile_reader_rule(p.get("raw_text", "")) if "normalized" not in p else p
    # budget interval
    low, high = budget_interval(parsed.get("budget_PKR"))
    city = (parsed.get("city") or "").lower()
    if not city:
        return {"rooms": [], "note":"City not found in profile; cannot search city-based listings."}
    candidates = []
    for L in listings:
        if L.get("availability","").lower() != "available":
            continue
        if (L.get("city") or "").lower() != city:
            continue
        rent = L.get("monthly_rent_PKR", 0)
        if rent < low or rent > high:
            continue
        mid = (low + high) / 2
        rent_score = 1 - abs(rent - mid)/(mid if mid>0 else 1)
        amen_score = min(1.0, len(L.get("amenities", []))/6.0)
        final_score = round(0.6*rent_score + 0.4*amen_score, 4)
        candidates.append((final_score, L))
    candidates_sorted = sorted(candidates, key=lambda x: x[0], reverse=True)
    out = [{"listing_id":c[1]["listing_id"], "area":c[1]["area"], "monthly_rent_PKR":c[1]["monthly_rent_PKR"], "amenities":c[1].get("amenities", []), "score":c[0]} for c in candidates_sorted[:top_n]]
    return {"rooms": out}

@app.post("/rooms/search", summary="Search room listings by free text or filters")
def search_rooms(req: RoomSearchRequest):
    # Normalize inputs and prefer raw_text-derived filters when provided
    def _norm_city(c: Optional[str]) -> str:
        c = (c or "").strip()
        if not c or c.lower() in {"string", "any", "null", "none"}:
            return ""
        return c.lower()

    def _norm_budget(v: Optional[int]) -> Optional[int]:
        try:
            iv = int(v) if v is not None else None
            return iv if iv and iv > 0 else None
        except Exception:
            return None

    city = _norm_city(req.city)
    bmin = _norm_budget(req.budget_min)
    bmax = _norm_budget(req.budget_max)
    bpk = _norm_budget(req.budget_PKR)
    low: Optional[int] = None
    high: Optional[int] = None

    # If raw_text is provided, parse and use it as primary source
    if (req.raw_text or "").strip():
        parsed = profile_reader_rule(req.raw_text or "")
        if not city and parsed.get("city"):
            city = (parsed.get("city") or "").lower()
        if bpk is None and (bmin is None or bmax is None) and parsed.get("budget_PKR"):
            low, high = budget_interval(parsed.get("budget_PKR"))

    # If budgets still unset, use structured values if valid
    if low is None or high is None:
        if bmin is not None and bmax is not None:
            low, high = int(bmin), int(bmax)
        elif bpk is not None:
            low, high = budget_interval(int(bpk))

    # Smart default if budget not provided: use per-city IQR or global median window
    if low is None or high is None:
        def _quantile(arr, q: float):
            if not arr:
                return None
            arr_sorted = sorted(arr)
            # use linear index approximation
            idx = int(q * (len(arr_sorted) - 1))
            idx = max(0, min(idx, len(arr_sorted) - 1))
            return arr_sorted[idx]

        def _city_rents(city_lower: str):
            return [
                L.get("monthly_rent_PKR", 0)
                for L in listings
                if L.get("availability", "").lower() == "available"
                and (L.get("city") or "").lower() == city_lower
                and L.get("monthly_rent_PKR")
            ]

        rents = _city_rents(city) if city else [
            L.get("monthly_rent_PKR", 0)
            for L in listings
            if L.get("availability", "").lower() == "available" and L.get("monthly_rent_PKR")
        ]

        if rents:
            q25 = _quantile(rents, 0.25)
            q50 = _quantile(rents, 0.50)
            q75 = _quantile(rents, 0.75)
            if q25 is not None and q75 is not None and q25 <= q75:
                low, high = int(q25), int(q75)
            elif q50 is not None:
                span = int(q50 * 0.2)
                low, high = max(0, int(q50) - span), int(q50) + span
            else:
                low, high = 0, 1_000_000_000
        else:
            low, high = 0, 1_000_000_000

    # Filter and score listings
    candidates = []
    for L in listings:
        if L.get("availability", "").lower() != "available":
            continue
        if city and (L.get("city") or "").lower() != city:
            continue
        rent = L.get("monthly_rent_PKR", 0)
        if rent < low or rent > high:
            continue
        mid = (low + high) / 2
        rent_score = 1 - abs(rent - mid) / (mid if mid > 0 else 1)
        amen_score = min(1.0, len(L.get("amenities", [])) / 6.0)
        final_score = round(0.6 * rent_score + 0.4 * amen_score, 4)
        candidates.append((final_score, L))

    candidates_sorted = sorted(candidates, key=lambda x: x[0], reverse=True)
    out = [
        {
            "listing_id": c[1]["listing_id"],
            "city": c[1].get("city"),
            "area": c[1].get("area"),
            "monthly_rent_PKR": c[1].get("monthly_rent_PKR"),
            "amenities": c[1].get("amenities", []),
            "score": c[0],
        }
        for c in candidates_sorted[: max(1, int(req.top_n))]
    ]

    return {
        "rooms": out,
        "applied_filters": {"city": city or None, "budget_min": low, "budget_max": high},
    }

@app.post("/match", summary="Detailed pairwise match (two profile ids) -> returns match, flags, explanation, rooms and trace")
def pairwise_match(req: MatchRequest):
    if req.profile_a not in profiles_by_id or req.profile_b not in profiles_by_id:
        raise HTTPException(status_code=404, detail="One or both profile ids not found")
    # run pipeline
    res = run_match_pipeline(req.profile_a, req.profile_b, degraded=req.degraded)
    return res

@app.get("/stats", summary="Dataset stats (profiles & listings quick statistics)")
def dataset_stats():
    cities = Counter((p.get("city") or "").title() for p in profiles)
    listing_cities = Counter((l.get("city") or "").title() for l in listings)
    rents = [l.get("monthly_rent_PKR",0) for l in listings if l.get("monthly_rent_PKR")]
    rents_sorted = sorted(rents)
    def quantile(arr, q):
        if not arr: return None
        i = int(q*len(arr))
        i = min(max(0,i), len(arr)-1)
        return arr[i]
    return {
        "profiles_count": len(profiles),
        "listings_count": len(listings),
        "profiles_by_city": dict(cities.most_common()),
        "listings_by_city": dict(listing_cities.most_common()),
        "rent_min": min(rents) if rents else None,
        "rent_25p": quantile(rents_sorted, 0.25),
        "rent_median": quantile(rents_sorted, 0.5),
        "rent_75p": quantile(rents_sorted, 0.75),
        "rent_max": max(rents) if rents else None
    }
