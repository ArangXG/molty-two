#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║          MOLTY ROYALE — AI AGENT BOT  v3.0                       ║
║          Intelligent Battle Royale Champion                      ║
║                                                                  ║
║  Strategy Priority (from SKILL.md):                             ║
║    1. SURVIVE  → Never die to Death Zone (absolute priority)    ║
║    2. WEAPON   → Best weapon before combat                       ║
║    3. KILL     → Hunt with calculated Win Probability            ║
║    4. LOOT     → Efficient post-kill looting                     ║
║    5. ECONOMY  → Smart room selection & balance management       ║
╚══════════════════════════════════════════════════════════════════╝
"""

import asyncio
import aiohttp
import logging
import json
import os
import sys
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

# ═══════════════════════════════════════════════════════════════
#  CONFIGURATION  (edit here or use environment variables)
# ═══════════════════════════════════════════════════════════════

API_BASE       = os.getenv("MOLTY_API_BASE",   "https://www.moltyroyale.com/api")
API_KEY        = os.getenv("MOLTY_API_KEY",    "YOUR_API_KEY_HERE")
AGENT_NAME     = os.getenv("MOLTY_AGENT_NAME", "ShadowStrike_v3")
LOG_LEVEL      = os.getenv("LOG_LEVEL",        "INFO")
TICK_INTERVAL  = float(os.getenv("TICK_INTERVAL", "1.0"))  # seconds per decision loop

# ═══════════════════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════════════════

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s  [%(levelname)-8s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/bot.log"),
    ],
)
log = logging.getLogger("MoltyBot")


# ═══════════════════════════════════════════════════════════════
#  CONSTANTS — tuned directly from SKILL.md rules
# ═══════════════════════════════════════════════════════════════

class State(Enum):
    IDLE         = "idle"
    ROOM_SCAN    = "room_scan"
    IN_LOBBY     = "in_lobby"
    ZONE_ESCAPE  = "zone_escape"
    WEAPON_HUNT  = "weapon_hunt"
    EXPLORING    = "exploring"
    TARGET_LOCK  = "target_lock"
    COMBAT       = "combat"
    LOOTING      = "looting"
    HEALING      = "healing"
    DEAD         = "dead"
    VICTORY      = "victory"

# Combat thresholds
WIN_PROB_ENGAGE    = 0.60   # Min win probability to engage enemy
WIN_PROB_DISENGAGE = 0.55   # Drop target if win prob falls below this
ESCAPE_PROB_MAX    = 0.40   # Only lock targets who can't easily escape
WEAPON_UPGRADE_PCT = 0.15   # Min weapon score improvement to swap (15%)
SAFE_PATH_MIN      = 0.65   # Min safe path probability for weapon chase
ZONE_CHASE_MAX_SEC = 3.0    # Max seconds to chase inside Death Zone
ZONE_ESCAPE_MIN    = 0.75   # Min escape prob needed for Death Zone chase

# HP thresholds
HP_USE_HEAL    = 60   # Auto-use strongest heal item at this % hp
HP_DISENGAGE   = 35   # Force disengage + reposition + heal
HP_ZONE_ABORT  = 60   # If HP < this AND near zone → escape first

# Inventory limits
MAX_HEAL_PER_TYPE = 3

# RVS system (Region Value Score)
RVS_BASE         = 1.0
RVS_FLOOR        = 0.5    # Abandon regions below this value
RVS_HIGH_WEAPON  = +0.3
RVS_KILL         = +0.2
RVS_FAIL_EXPLORE = -0.3   # After 2 failed explores
RVS_ZONE_PRONE   = -0.5
RVS_AMBUSH       = -0.2

# Weapon tier multipliers
TIER_MULT = {
    "legendary": 3.0,
    "epic":      2.2,
    "rare":      1.5,
    "uncommon":  1.2,
    "common":    1.0,
    "fists":     0.3,
}

HEAL_PRIORITY = ["mega_shield", "large_medkit", "medkit", "bandage", "small_heal"]


# ═══════════════════════════════════════════════════════════════
#  DATA MODELS
# ═══════════════════════════════════════════════════════════════

@dataclass
class Weapon:
    name:     str
    dps:      float = 0.0
    accuracy: float = 1.0
    range:    float = 1.0
    tier:     str   = "common"

    @property
    def score(self) -> float:
        mult = TIER_MULT.get(self.tier.lower(), 1.0)
        return self.dps * self.accuracy * self.range * mult

    def is_upgrade_over(self, other: Optional["Weapon"]) -> bool:
        if other is None:
            return True
        if other.score <= 0:
            return self.score > 0
        return (self.score - other.score) / other.score >= WEAPON_UPGRADE_PCT


@dataclass
class Enemy:
    id:       str
    hp:       float = 100.0
    max_hp:   float = 100.0
    dps:      float = 10.0
    distance: float = 50.0
    in_zone:  bool  = False
    position: dict  = field(default_factory=dict)

    @property
    def hp_pct(self) -> float:
        return (self.hp / self.max_hp) * 100 if self.max_hp else 0


@dataclass
class Zone:
    distance:     float = 999.0  # agent's distance to safe boundary
    shrink_timer: float = 999.0  # seconds until next shrink
    direction:    str   = ""     # direction towards safe zone center
    is_safe:      bool  = True   # is agent currently inside safe zone?
    shrink_speed: float = 1.0    # damage per second from zone


@dataclass
class GameState:
    # Agent vitals
    hp:             float  = 100.0
    max_hp:         float  = 100.0
    balance:        float  = 0.0
    kills:          int    = 0
    weapon:         Optional[Weapon] = None
    inventory:      dict   = field(default_factory=dict)  # item → count
    position:       dict   = field(default_factory=dict)  # {x, y, region}

    # Zone
    zone:           Zone   = field(default_factory=Zone)

    # Vision
    vision_modifier: float = 1.0  # 0.0=blind, 1.0=full sight

    # World data
    enemies:         list = field(default_factory=list)   # list[Enemy]
    loot_nearby:     list = field(default_factory=list)   # list[dict]
    weapons_nearby:  list = field(default_factory=list)   # list[Weapon]
    current_region:  str  = ""

    # Match info
    players_alive:  int   = 0
    match_id:       str   = ""
    tick:           int   = 0

    # Internal FSM
    state:          State = State.IDLE
    target_id:      Optional[str]   = None
    locked_target:  Optional[Enemy] = None

    @property
    def hp_pct(self) -> float:
        return (self.hp / self.max_hp) * 100 if self.max_hp else 0

    @property
    def best_heal(self) -> Optional[str]:
        for item in HEAL_PRIORITY:
            if self.inventory.get(item, 0) > 0:
                return item
        return None


# ═══════════════════════════════════════════════════════════════
#  REGION VALUE SYSTEM (RVS) — AI learns map efficiency over time
# ═══════════════════════════════════════════════════════════════

class RegionMemory:
    def __init__(self):
        self._rvs:        dict = {}  # region → float score
        self._explores:   dict = {}  # region → int count
        self._loot_found: dict = {}  # region → int total loot found

    def rvs(self, region: str) -> float:
        return self._rvs.get(region, RVS_BASE)

    def record_explore(self, region: str, loot_found: int):
        """Call after each explore. loot_found = number of meaningful items found."""
        self._explores[region]   = self._explores.get(region, 0) + 1
        self._loot_found[region] = self._loot_found.get(region, 0) + loot_found

        count      = self._explores[region]
        total_loot = self._loot_found[region]
        if count >= 2 and total_loot == 0:
            self._adjust(region, RVS_FAIL_EXPLORE, "2 failed explores")

    def record_event(self, region: str, event: str):
        delta_map = {
            "high_tier_weapon": RVS_HIGH_WEAPON,
            "kill":             RVS_KILL,
            "zone_prone":       RVS_ZONE_PRONE,
            "ambush":           RVS_AMBUSH,
        }
        delta = delta_map.get(event, 0)
        if delta:
            self._adjust(region, delta, event)

    def is_worthwhile(self, region: str) -> bool:
        return self.rvs(region) >= RVS_FLOOR

    def best_region(self, candidates: list) -> Optional[str]:
        worth = [r for r in candidates if self.is_worthwhile(r)]
        pool  = worth if worth else candidates
        return max(pool, key=self.rvs) if pool else None

    def _adjust(self, region: str, delta: float, reason: str):
        old = self.rvs(region)
        self._rvs[region] = max(0.0, min(2.0, old + delta))
        log.debug(f"[RVS] {region}: {old:.2f} → {self.rvs(region):.2f}  ({reason})")

    def summary(self) -> dict:
        return {r: round(v, 2) for r, v in self._rvs.items()}


# ═══════════════════════════════════════════════════════════════
#  DECISION ENGINE — pure strategy logic, zero API calls
# ═══════════════════════════════════════════════════════════════

class DecisionEngine:
    """
    Stateless strategy calculator.
    Takes a GameState → returns the best Action dict.

    Priority order matches SKILL.md exactly:
      1. Zone escape
      2. Heal (critical)
      3. Weapon hunt (if better weapon nearby)
      4. Heal (normal)
      5. Target lock & combat
      6. Explore best region
      7. Loot
      8. Patrol (fallback)
    """

    def __init__(self, memory: RegionMemory):
        self.memory = memory

    def decide(self, gs: GameState) -> dict:

        # ①  ABSOLUTE PRIORITY — Zone escape
        if self._zone_critical(gs):
            return self._zone_escape_action(gs)

        # ②  Critical heal (HP < 35%)
        if gs.hp_pct < HP_DISENGAGE and gs.best_heal:
            return self._heal_action(gs)

        # ③  Weapon hunt — upgrade if ≥15% better AND safe path
        best_w = self._best_nearby_weapon(gs)
        if best_w and best_w.is_upgrade_over(gs.weapon):
            if (self._safe_path_prob(gs) >= SAFE_PATH_MIN
                    and not self._weapon_in_zone_trajectory(gs)):
                log.info(f"[WEAPON] Hunting {best_w.name} (score {best_w.score:.1f})")
                return {"action": "move_to_weapon", "weapon_name": best_w.name}

        # ④  Normal heal (HP < 60%)
        if gs.hp_pct < HP_USE_HEAL and gs.best_heal:
            return self._heal_action(gs)

        # ⑤  Target acquisition & combat
        target = self._select_target(gs)
        if target:
            gs.locked_target = target
            gs.target_id     = target.id

            if target.in_zone:
                kill_t  = self._kill_time(gs, target)
                esc_p   = self._self_escape_prob(gs)
                if kill_t <= ZONE_CHASE_MAX_SEC and esc_p >= ZONE_ESCAPE_MIN:
                    log.info(f"[COMBAT] Zone-chase {target.id} ({kill_t:.1f}s kill, esc={esc_p:.0%})")
                    return {"action": "attack", "target_id": target.id}
                else:
                    log.info(f"[COMBAT] Refused zone-chase {target.id} (too risky)")
                    gs.locked_target = None
                    gs.target_id     = None
            else:
                wp = self._win_prob(gs, target)
                log.info(f"[COMBAT] Attacking {target.id} (win_prob={wp:.0%}, hp={target.hp_pct:.0f}%)")
                return {"action": "attack", "target_id": target.id}

        # ⑥  Explore best region
        region = self._choose_region(gs)
        if region and region != gs.current_region:
            log.info(f"[EXPLORE] Moving to region: {region}")
            return {"action": "move_to_region", "region": region}

        # ⑦  Pick up loot
        loot = self._pick_loot(gs)
        if loot:
            log.info(f"[LOOT] Picking up: {loot.get('item')}")
            return {"action": "pick_loot", "item_id": loot.get("id")}

        # ⑧  Fallback — stay active
        return {"action": "patrol"}

    # ── Zone helpers ──────────────────────────────────────────

    def _zone_critical(self, gs: GameState) -> bool:
        if not gs.zone.is_safe:
            return True
        if gs.zone.distance < 50 and gs.zone.shrink_timer < 10:
            return True
        if gs.hp_pct < HP_ZONE_ABORT and gs.zone.distance < 80:
            return True
        return False

    def _zone_escape_action(self, gs: GameState) -> dict:
        log.warning(
            f"[ZONE] ⚠ ESCAPE! dist={gs.zone.distance:.0f}m "
            f"timer={gs.zone.shrink_timer:.0f}s hp={gs.hp_pct:.0f}%"
        )
        action = {
            "action":    "escape_zone",
            "direction": gs.zone.direction or "safe_zone_center",
            "priority":  "sprint",
        }
        # Heal on the run only if in extreme danger
        if gs.hp_pct < 30 and gs.best_heal:
            action["use_heal"] = gs.best_heal
        return action

    # ── Weapon helpers ────────────────────────────────────────

    def _best_nearby_weapon(self, gs: GameState) -> Optional[Weapon]:
        if not gs.weapons_nearby:
            return None
        return max(gs.weapons_nearby, key=lambda w: w.score)

    def _safe_path_prob(self, gs: GameState) -> float:
        d = gs.zone.distance
        if d > 200: return 0.90
        if d > 100: return 0.75
        if d > 50:  return 0.55
        return 0.30

    def _weapon_in_zone_trajectory(self, gs: GameState) -> bool:
        return gs.zone.distance < 40 and gs.zone.shrink_timer < 8

    # ── Target selection ──────────────────────────────────────

    def _select_target(self, gs: GameState) -> Optional[Enemy]:
        """
        Win Probability =
          (My DPS × My HP × Position Advantage × Vision Advantage)
          / (Enemy DPS × Enemy HP × Distance Risk)

        Select: win_prob ≥ 60% AND escape_prob ≤ 40%
        Prefer weakest + nearest for fastest kills
        """
        best        = None
        best_score  = 0.0

        for enemy in gs.enemies:
            if enemy.in_zone:
                continue

            wp = self._win_prob(gs, enemy)
            ep = self._enemy_escape_prob(enemy)

            if wp >= WIN_PROB_ENGAGE and ep <= ESCAPE_PROB_MAX:
                # Composite score: high win-prob, low hp target, close range
                score = wp * (1.0 - enemy.hp_pct / 100) / max(enemy.distance, 1)
                if score > best_score:
                    best_score = score
                    best       = enemy

        return best

    def _win_prob(self, gs: GameState, enemy: Enemy) -> float:
        my_dps  = gs.weapon.dps if gs.weapon else 5.0
        my_hp   = gs.hp
        pos_adv = self._position_advantage(gs, enemy)
        vis_adv = gs.vision_modifier

        # Vision adjustment from SKILL.md
        if gs.vision_modifier < 0.5:
            # Low visibility: prefer close-range, penalty at distance
            if enemy.distance > 60:
                vis_adv *= 0.6

        e_dps  = max(enemy.dps, 0.1)
        e_hp   = max(enemy.hp, 0.1)
        dist_r = max(1.0, enemy.distance / 50.0)

        numerator   = my_dps * my_hp * pos_adv * vis_adv
        denominator = e_dps * e_hp * dist_r
        raw = numerator / denominator
        # Sigmoid-like clamp to 0–1
        return min(1.0, max(0.0, raw / (raw + 1.0)))

    def _position_advantage(self, gs: GameState, enemy: Enemy) -> float:
        # Placeholder — extend with real map/cover data
        return 1.0

    def _enemy_escape_prob(self, enemy: Enemy) -> float:
        if enemy.hp_pct < 25:   return 0.10
        if enemy.distance > 100: return 0.70
        return 0.35

    def _kill_time(self, gs: GameState, enemy: Enemy) -> float:
        my_dps = gs.weapon.dps if gs.weapon else 5.0
        return enemy.hp / my_dps if my_dps > 0 else 999.0

    def _self_escape_prob(self, gs: GameState) -> float:
        d = gs.zone.distance
        if d < 20:   return 0.30
        if d < 60:   return 0.60
        return 0.85

    # ── Heal helpers ─────────────────────────────────────────

    def _heal_action(self, gs: GameState) -> dict:
        item = gs.best_heal
        log.info(f"[HEAL] Using {item} (HP={gs.hp_pct:.0f}%)")
        return {"action": "use_item", "item": item}

    # ── Region helpers ────────────────────────────────────────

    def _choose_region(self, gs: GameState) -> Optional[str]:
        known = list(self.memory._rvs.keys())
        if not known:
            known = ["central", "north", "south", "east", "west"]
        return self.memory.best_region(known)

    # ── Loot helpers ─────────────────────────────────────────

    def _pick_loot(self, gs: GameState) -> Optional[dict]:
        if not gs.loot_nearby:
            return None
        # Prioritize heals when HP low
        if gs.hp_pct < HP_USE_HEAL:
            for item in gs.loot_nearby:
                name = item.get("item", "")
                if name in HEAL_PRIORITY and gs.inventory.get(name, 0) < MAX_HEAL_PER_TYPE:
                    return item
        # Otherwise any uncapped loot
        for item in gs.loot_nearby:
            name = item.get("item", "")
            if gs.inventory.get(name, 0) < MAX_HEAL_PER_TYPE:
                return item
        return None

    def post_kill_actions(self, gs: GameState, enemy_id: str) -> list:
        """Ordered actions after a kill per SKILL.md protocol."""
        return [
            {"action": "loot_enemy",    "enemy_id": enemy_id},
            {"action": "reload"},
        ]


# ═══════════════════════════════════════════════════════════════
#  ROOM INTELLIGENCE SYSTEM — pre-game smart room selection
# ═══════════════════════════════════════════════════════════════

class RoomSelector:
    """
    SKILL.md rules:
      - Skip full rooms (current == max)
      - Skip paid rooms if balance < cost
      - Never reduce balance recklessly
      - Prefer high-player-count for kill potential
    """

    def select(self, rooms: list, balance: float) -> Optional[dict]:
        available = []
        for raw_room in rooms:
            # Safety: normalize to dict — API may return plain strings (room IDs)
            if isinstance(raw_room, str):
                room = {"id": raw_room, "current_players": 0, "max_players": 99,
                        "type": "free", "entry_cost": 0}
            elif isinstance(raw_room, dict):
                # Normalise common field name variants
                room = raw_room
                room.setdefault("id",              room.get("room_id") or room.get("roomId") or "")
                room.setdefault("current_players", room.get("players") or room.get("playerCount") or 0)
                room.setdefault("max_players",     room.get("maxPlayers") or room.get("capacity") or 99)
                room.setdefault("type",            room.get("roomType") or "free")
                room.setdefault("entry_cost",      room.get("cost") or room.get("fee") or 0)
            else:
                log.debug(f"[ROOM] Skipping unknown room type: {type(raw_room)}")
                continue

            current = int(room.get("current_players", 0))
            max_p   = int(room.get("max_players", 99))
            rtype   = str(room.get("type", "free")).lower()
            cost    = float(room.get("entry_cost", 0))
            rid     = room.get("id", "?")

            if current >= max_p:
                log.debug(f"[ROOM] Skip '{rid}' — FULL ({current}/{max_p})")
                continue

            if rtype == "paid" and balance < cost:
                log.debug(f"[ROOM] Skip '{rid}' — PAID ${cost}, balance=${balance:.2f}")
                continue

            available.append(room)

        if not available:
            log.warning("[ROOM] No suitable rooms found!")
            return None

        # Prefer most populated room (more kills possible)
        best = max(available, key=lambda r: int(r.get("current_players", 0)))
        log.info(
            f"[ROOM] Selected '{best.get('id')}' — "
            f"{best.get('current_players')}/{best.get('max_players')} players, "
            f"type={best.get('type','free')}, cost={best.get('entry_cost',0)}"
        )
        return best


# ═══════════════════════════════════════════════════════════════
#  API CLIENT — async HTTP wrapper
# ═══════════════════════════════════════════════════════════════

class MoltyClient:
    """
    Async HTTP client for Molty Royale API.
    Endpoint paths are best-guess based on REST conventions.
    Update them to match the real /docs once you have access.
    """

    def __init__(self, base: str, key: str, session: aiohttp.ClientSession):
        self.base    = base.rstrip("/")
        self.session = session
        self.headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type":  "application/json",
            "User-Agent":    f"MoltyBot/{AGENT_NAME}/3.0",
        }

    async def _req(self, method: str, path: str, **kwargs) -> Optional[dict]:
        url = f"{self.base}{path}"
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with self.session.request(
                method, url, headers=self.headers, timeout=timeout, **kwargs
            ) as r:
                text = await r.text()
                # Always log raw response at DEBUG level so we can diagnose
                log.debug(f"[API] {method} {path} → HTTP {r.status} | body: {text[:300]}")
                if r.status in (200, 201):
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return {"raw": text}
                elif r.status == 404:
                    log.debug(f"[API] 404 {path} — endpoint not found")
                elif r.status == 401:
                    log.error(f"[API] 401 UNAUTHORIZED — check your API key!")
                elif r.status == 403:
                    log.error(f"[API] 403 FORBIDDEN — API key valid but access denied")
                else:
                    log.warning(f"[API] {method} {path} → HTTP {r.status}: {text[:200]}")
        except asyncio.TimeoutError:
            log.error(f"[API] Timeout on {method} {path}")
        except aiohttp.ClientConnectorError as e:
            log.error(f"[API] Cannot connect to {url} — check MOLTY_API_BASE: {e}")
        except aiohttp.ClientError as e:
            log.error(f"[API] Connection error {method} {path}: {e}")
        return None

    # Rooms
    async def list_rooms(self) -> list:
        # Try multiple possible endpoint paths
        data = None
        for endpoint in ["/rooms", "/lobby", "/lobby/rooms", "/room", "/v1/rooms"]:
            data = await self._req("GET", endpoint)
            if data is not None:
                log.debug(f"[ROOM] Working endpoint: {endpoint} | type={type(data).__name__} | raw={str(data)[:200]}")
                break

        if data is None:
            log.warning("[ROOM] All room endpoints returned None — check API_BASE and API_KEY")
            return []

        # Unwrap dict wrapper — try all common key names
        if isinstance(data, dict):
            raw_list = (data.get("rooms")
                        or data.get("data")
                        or data.get("result")
                        or data.get("list")
                        or data.get("items")
                        or [])
            # Single room dict
            if not raw_list and ("id" in data or "room_id" in data or "roomId" in data):
                raw_list = [data]
            if not raw_list:
                log.warning(f"[ROOM] dict response but no known list key. Keys: {list(data.keys())} | raw: {str(data)[:300]}")
                return []
        elif isinstance(data, list):
            raw_list = data
        else:
            log.warning(f"[ROOM] Unexpected response type: {type(data)} | value: {str(data)[:200]}")
            return []

        # Normalize each room item
        rooms = []
        for item in raw_list:
            if isinstance(item, str):
                # Plain string room ID — fetch details
                detail = await self._req("GET", f"/rooms/{item}")
                if detail and isinstance(detail, dict):
                    detail.setdefault("id", item)
                    rooms.append(self._normalize_room(detail))
                else:
                    # Minimal fallback — selector will still work
                    rooms.append({
                        "id": item, "current_players": 0,
                        "max_players": 99, "type": "free", "entry_cost": 0,
                    })
            elif isinstance(item, dict):
                rooms.append(self._normalize_room(item))
            elif isinstance(item, (int, float)):
                rooms.append({
                    "id": str(item), "current_players": 0,
                    "max_players": 99, "type": "free", "entry_cost": 0,
                })
            else:
                log.debug(f"[ROOM] Unknown item type: {type(item)} = {item}")

        log.info(f"[ROOM] Total rooms available: {len(rooms)}")
        return rooms

    @staticmethod
    def _normalize_room(room: dict) -> dict:
        """Normalize field name variants into standard keys."""
        room.setdefault("id",              room.get("room_id") or room.get("roomId") or room.get("_id") or "")
        room.setdefault("current_players", room.get("players") or room.get("playerCount") or room.get("currentPlayers") or 0)
        room.setdefault("max_players",     room.get("maxPlayers") or room.get("max") or room.get("capacity") or room.get("size") or 99)
        room.setdefault("type",            room.get("roomType") or room.get("room_type") or "free")
        room.setdefault("entry_cost",      room.get("cost") or room.get("fee") or room.get("price") or room.get("entryCost") or 0)
        return room

    async def get_room(self, room_id: str) -> Optional[dict]:
        return await self._req("GET", f"/rooms/{room_id}")

    async def join_room(self, room_id: str) -> Optional[dict]:
        return await self._req("POST", f"/rooms/{room_id}/join", json={"agent": AGENT_NAME})

    async def leave_room(self, room_id: str) -> Optional[dict]:
        return await self._req("POST", f"/rooms/{room_id}/leave")

    # Match
    async def get_state(self, match_id: str) -> Optional[dict]:
        return await self._req("GET", f"/matches/{match_id}/state")

    async def send_action(self, match_id: str, action: dict) -> Optional[dict]:
        return await self._req("POST", f"/matches/{match_id}/action", json=action)

    # Account
    async def get_balance(self) -> float:
        data = await self._req("GET", "/account/balance")
        return float(data.get("balance", 0)) if data else 0.0

    async def get_profile(self) -> Optional[dict]:
        return await self._req("GET", "/account/profile")


# ═══════════════════════════════════════════════════════════════
#  STATE PARSER — raw API JSON → GameState
# ═══════════════════════════════════════════════════════════════

class StateParser:
    """
    Converts the raw JSON from the Molty API into a clean GameState.
    Field names are best-guess — adjust to real API schema.
    """

    @staticmethod
    def parse(raw: dict, prev: Optional[GameState] = None) -> GameState:
        gs = GameState() if prev is None else deepcopy(prev)

        agent = raw.get("agent", raw)

        # Vitals
        gs.hp      = float(agent.get("hp",      gs.hp))
        gs.max_hp  = float(agent.get("max_hp",  gs.max_hp))
        gs.balance = float(agent.get("balance", gs.balance))
        gs.kills   = int(agent.get("kills",     gs.kills))
        gs.tick    = int(raw.get("tick",         gs.tick + 1))

        # Position
        if "position" in agent:
            gs.position       = agent["position"]
            gs.current_region = agent["position"].get("region", gs.current_region)

        # Zone
        z = raw.get("zone", {})
        gs.zone = Zone(
            distance     = float(z.get("distance_to_safe", gs.zone.distance)),
            shrink_timer = float(z.get("shrink_timer",     gs.zone.shrink_timer)),
            direction    = z.get("safe_direction",          gs.zone.direction),
            is_safe      = bool(z.get("agent_is_safe",      gs.zone.is_safe)),
            shrink_speed = float(z.get("damage_per_sec",    gs.zone.shrink_speed)),
        )

        # Vision
        gs.vision_modifier = float(raw.get("vision_modifier", gs.vision_modifier))

        # Weapon
        w = agent.get("weapon")
        if w:
            gs.weapon = Weapon(
                name     = w.get("name",     "unknown"),
                dps      = float(w.get("dps",      0)),
                accuracy = float(w.get("accuracy", 1)),
                range    = float(w.get("range",    1)),
                tier     = w.get("tier",     "common"),
            )

        # Inventory
        inv = agent.get("inventory", [])
        if isinstance(inv, list):
            gs.inventory = {e["item"]: int(e.get("count", 1)) for e in inv}
        elif isinstance(inv, dict):
            gs.inventory = inv

        # Enemies
        gs.enemies = []
        for e in raw.get("visible_enemies", []):
            gs.enemies.append(Enemy(
                id       = str(e.get("id", "")),
                hp       = float(e.get("hp",       100)),
                max_hp   = float(e.get("max_hp",   100)),
                dps      = float(e.get("dps",      10)),
                distance = float(e.get("distance", 50)),
                in_zone  = bool(e.get("in_zone",   False)),
                position = e.get("position", {}),
            ))

        # Loot nearby
        gs.loot_nearby    = raw.get("loot_nearby", [])

        # Weapons nearby
        gs.weapons_nearby = []
        for w in raw.get("weapons_nearby", []):
            gs.weapons_nearby.append(Weapon(
                name     = w.get("name",     "unknown"),
                dps      = float(w.get("dps",      0)),
                accuracy = float(w.get("accuracy", 1)),
                range    = float(w.get("range",    1)),
                tier     = w.get("tier",     "common"),
            ))

        # Match
        gs.players_alive = int(raw.get("players_alive", gs.players_alive))
        gs.match_id      = raw.get("match_id", gs.match_id)

        return gs


# ═══════════════════════════════════════════════════════════════
#  MAIN BOT
# ═══════════════════════════════════════════════════════════════

class MoltyBot:

    def __init__(self):
        self.memory   = RegionMemory()
        self.engine   = DecisionEngine(self.memory)
        self.selector = RoomSelector()
        self.client:  Optional[MoltyClient] = None
        self.gs:      GameState = GameState()
        self.session: Optional[aiohttp.ClientSession] = None

        self.room_id:    Optional[str] = None
        self.match_id:   Optional[str] = None
        self.err_streak: int = 0
        self.stat_matches = 0
        self.stat_kills   = 0

    # ── Startup ───────────────────────────────────────────────

    async def start(self):
        log.info("=" * 60)
        log.info(f"  🎮  MOLTY ROYALE BOT  |  Agent: {AGENT_NAME}")
        log.info(f"  🌐  API: {API_BASE}")
        log.info("=" * 60)

        connector    = aiohttp.TCPConnector(limit=10, enable_cleanup_closed=True)
        self.session = aiohttp.ClientSession(connector=connector)
        self.client  = MoltyClient(API_BASE, API_KEY, self.session)

        try:
            await self._run()
        except (KeyboardInterrupt, asyncio.CancelledError):
            log.info("[BOT] Shutdown signal received.")
        except Exception as e:
            log.critical(f"[BOT] Fatal error: {e}", exc_info=True)
        finally:
            log.info("[BOT] Cleaning up...")
            try:
                if self.session and not self.session.closed:
                    await self.session.close()
            except Exception:
                pass
            self._print_summary()

    # ── Main loop ─────────────────────────────────────────────

    async def _run(self):
        while True:
            try:
                # Refresh balance
                bal = await self.client.get_balance()
                if bal is not None:
                    self.gs.balance = bal

                if not self.room_id:
                    await self._phase_room()
                    await asyncio.sleep(2)
                else:
                    await self._phase_match()

                self.err_streak = 0

            except (KeyboardInterrupt, asyncio.CancelledError):
                # Propagate shutdown signals — do NOT swallow them
                raise
            except Exception as e:
                self.err_streak += 1
                log.error(f"[LOOP] Error #{self.err_streak}: {e}", exc_info=True)
                wait = min(30, self.err_streak * 5)
                await asyncio.sleep(wait)

    # ── Room phase ────────────────────────────────────────────

    async def _phase_room(self):
        log.info("[ROOM] 🔍 Scanning rooms...")
        rooms = await self.client.list_rooms()

        if not rooms:
            log.warning("[ROOM] No rooms found, retrying in 5s...")
            await asyncio.sleep(5)
            return

        room = self.selector.select(rooms, self.gs.balance)
        if not room:
            await asyncio.sleep(10)
            return

        rid    = room.get("id") or room.get("room_id")
        result = await self.client.join_room(rid)

        if result is not None:
            self.room_id  = rid
            # join result might be a dict OR a plain string/id
            if isinstance(result, dict):
                self.match_id = (result.get("match_id") or result.get("id")
                                 or result.get("matchId") or rid)
            else:
                self.match_id = str(result) if result else rid
            self.stat_matches += 1
            log.info(f"[ROOM] ✅ Joined {rid} | match_id={self.match_id}")
        else:
            log.warning(f"[ROOM] ❌ Failed to join {rid}")

    # ── Match phase ───────────────────────────────────────────

    async def _phase_match(self):
        mid = self.match_id or self.room_id

        raw = await self.client.get_state(mid)
        if raw is None:
            await asyncio.sleep(TICK_INTERVAL)
            return

        prev_kills = self.gs.kills
        self.gs    = StateParser.parse(raw, self.gs)

        # Detect kills
        new_kills = self.gs.kills - prev_kills
        if new_kills > 0:
            self.stat_kills += new_kills
            log.info(f"[KILL] 💀 +{new_kills} kill(s) | Match total: {self.gs.kills}")
            self.memory.record_event(self.gs.current_region, "kill")

        # Check for match end
        status = raw.get("status", "")
        if status in ("finished", "ended", "game_over") or self.gs.players_alive <= 1:
            await self._end_match(raw)
            return

        if self.gs.hp <= 0 or status == "dead":
            log.info("[MATCH] ☠ Eliminated.")
            await self._end_match(raw)
            return

        # Make and send decision
        action = self.engine.decide(self.gs)
        log.debug(f"[ACT] tick={self.gs.tick} hp={self.gs.hp_pct:.0f}% zone={self.gs.zone.distance:.0f}m → {action}")

        result = await self.client.send_action(mid, action)
        self._process_result(result, action)

        await asyncio.sleep(TICK_INTERVAL)

    def _process_result(self, result: Optional[dict], action: dict):
        if result is None:
            return

        act = action.get("action", "")

        # Weapon acquired
        if act == "move_to_weapon" and result.get("weapon_acquired"):
            w = result["weapon_acquired"]
            nw = Weapon(
                name     = w.get("name", "unknown"),
                dps      = float(w.get("dps",      0)),
                accuracy = float(w.get("accuracy", 1)),
                range    = float(w.get("range",    1)),
                tier     = w.get("tier",    "common"),
            )
            self.gs.weapon = nw
            log.info(f"[WEAPON] ✅ Got {nw.name} (score={nw.score:.1f}, tier={nw.tier})")
            if nw.tier in ("legendary", "epic"):
                self.memory.record_event(self.gs.current_region, "high_tier_weapon")

        # RVS loot tracking
        if act in ("move_to_region", "explore"):
            loot_n = result.get("items_found", 0)
            self.memory.record_explore(self.gs.current_region, loot_n)

        # Ambush penalty
        if result.get("ambushed"):
            self.memory.record_event(self.gs.current_region, "ambush")

    async def _end_match(self, raw: dict):
        rank  = raw.get("rank", "?")
        kills = self.gs.kills
        log.info(f"[MATCH] 🏁 Ended | Rank: #{rank} | Kills: {kills}")
        log.info(f"[MEMORY] RVS map: {self.memory.summary()}")

        if self.room_id:
            await self.client.leave_room(self.room_id)

        self.room_id  = None
        self.match_id = None
        self.gs       = GameState()
        await asyncio.sleep(3)

    def _print_summary(self):
        log.info("=" * 60)
        log.info("  📊  SESSION SUMMARY")
        log.info(f"  Matches played : {self.stat_matches}")
        log.info(f"  Total kills    : {self.stat_kills}")
        log.info(f"  Region memory  : {self.memory.summary()}")
        log.info("=" * 60)


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if API_KEY == "YOUR_API_KEY_HERE":
        log.warning("⚠  API key not set! Use: export MOLTY_API_KEY=your_key")
        log.warning("   Then run: python bot.py")

    try:
        asyncio.run(MoltyBot().start())
    except KeyboardInterrupt:
        # Clean Ctrl+C — suppress traceback spam
        log.info("[BOT] 👋 Stopped. Goodbye!")
    except Exception as e:
        log.critical(f"[BOT] Crashed: {e}", exc_info=True)
        sys.exit(1)
